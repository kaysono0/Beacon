#import "synthetic_video_clip.h"

#import <AVFoundation/AVFoundation.h>

#include <cstdlib>

NSString* BeaconSyntheticVideoClipPath() {
  const char* override_path = getenv("BEACON_SYNTHETIC_VIDEO_CLIP_PATH");
  if (override_path != nullptr && override_path[0] != '\0') {
    return [NSString stringWithUTF8String:override_path];
  }
  return @"test_cases/media/animated_clip.mp4";
}

NSString* BeaconSyntheticPairedMediaClipPath() {
  const char* override_path = getenv("BEACON_SYNTHETIC_PAIRED_MEDIA_CLIP_PATH");
  if (override_path != nullptr && override_path[0] != '\0') {
    return [NSString stringWithUTF8String:override_path];
  }
  return @"test_cases/sample_960x400_ocean_with_audio.mp4";
}

NSString* BeaconSyntheticAudioClipPath() {
  const char* override_path = getenv("BEACON_SYNTHETIC_AUDIO_CLIP_PATH");
  if (override_path != nullptr && override_path[0] != '\0') {
    return [NSString stringWithUTF8String:override_path];
  }
  return @"test_cases/sample_960x400_ocean_audio.m4a";
}

@implementation BeaconSyntheticVideoClip {
  NSString* path_;
  AVAsset* asset_;
  AVAssetTrack* video_track_;
  AVAssetReader* reader_;
  AVAssetReaderTrackOutput* output_;
  CVPixelBufferRef first_frame_;
}

- (instancetype)initWithPath:(NSString*)path {
  self = [super init];
  if (self == nil || path.length == 0 || ![[NSFileManager defaultManager] fileExistsAtPath:path]) {
    return nil;
  }
  path_ = [path copy];
  asset_ = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:path_] options:nil];
  video_track_ = [[asset_ tracksWithMediaType:AVMediaTypeVideo] firstObject];
  if (video_track_ == nil || ![self startReader]) {
    return nil;
  }
  first_frame_ = [self copyFrameFromReader];
  if (first_frame_ == nil) {
    return nil;
  }
  return self;
}

- (BOOL)startReader {
  NSError* error = nil;
  reader_ = [[AVAssetReader alloc] initWithAsset:asset_ error:&error];
  if (reader_ == nil || error != nil) {
    return NO;
  }
  output_ = [[AVAssetReaderTrackOutput alloc]
      initWithTrack:video_track_
      outputSettings:@{(id)kCVPixelBufferPixelFormatTypeKey : @(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)}];
  output_.alwaysCopiesSampleData = NO;
  if (![reader_ canAddOutput:output_]) {
    return NO;
  }
  [reader_ addOutput:output_];
  return [reader_ startReading];
}

- (CVPixelBufferRef)copyFrameFromReader {
  CMSampleBufferRef sample = [output_ copyNextSampleBuffer];
  if (sample == nil) {
    [reader_ cancelReading];
    if (![self startReader]) {
      return nil;
    }
    sample = [output_ copyNextSampleBuffer];
  }
  if (sample == nil) {
    return nil;
  }
  CVPixelBufferRef buffer = CMSampleBufferGetImageBuffer(sample);
  if (buffer != nil) {
    CFRetain(buffer);
  }
  CFRelease(sample);
  return buffer;
}

- (CVPixelBufferRef)copyNextFrame {
  if (first_frame_ != nil) {
    CVPixelBufferRef frame = first_frame_;
    first_frame_ = nil;
    return frame;
  }
  return [self copyFrameFromReader];
}

- (void)dealloc {
  if (first_frame_ != nil) {
    CFRelease(first_frame_);
  }
}

- (int)width {
  return static_cast<int>(video_track_.naturalSize.width);
}

- (int)height {
  return static_cast<int>(video_track_.naturalSize.height);
}

@end

@implementation BeaconSyntheticAudioClip {
  AVAsset* asset_;
  AVAssetTrack* audio_track_;
  AVAssetReader* reader_;
  AVAssetReaderTrackOutput* output_;
  NSMutableData* pending_pcm_;
  NSUInteger pending_offset_;
  int sample_rate_;
  int channels_;
  NSUInteger bytes_per_frame_;
  BOOL pcm_format_verified_;
}

- (instancetype)initWithPath:(NSString*)path {
  self = [super init];
  if (self == nil || path.length == 0 || ![[NSFileManager defaultManager] fileExistsAtPath:path]) {
    return nil;
  }
  sample_rate_ = 48000;
  channels_ = 2;
  bytes_per_frame_ = 4;
  pcm_format_verified_ = NO;
  asset_ = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:path] options:nil];
  audio_track_ = [[asset_ tracksWithMediaType:AVMediaTypeAudio] firstObject];
  if (audio_track_ == nil) {
    return nil;
  }
  pending_pcm_ = [NSMutableData data];
  return [self startReader] ? self : nil;
}

- (BOOL)startReader {
  NSError* error = nil;
  reader_ = [[AVAssetReader alloc] initWithAsset:asset_ error:&error];
  if (reader_ == nil || error != nil) {
    return NO;
  }
  output_ = [[AVAssetReaderTrackOutput alloc] initWithTrack:audio_track_ outputSettings:@{
      AVFormatIDKey : @(kAudioFormatLinearPCM),
      AVSampleRateKey : @48000,
      AVNumberOfChannelsKey : @2,
      AVLinearPCMBitDepthKey : @16,
      AVLinearPCMIsFloatKey : @NO,
      AVLinearPCMIsBigEndianKey : @NO,
      AVLinearPCMIsNonInterleavedKey : @NO,
  }];
  output_.alwaysCopiesSampleData = NO;
  if (![reader_ canAddOutput:output_]) {
    return NO;
  }
  [reader_ addOutput:output_];
  return [reader_ startReading];
}

- (BOOL)appendNextPCMBuffer {
  CMSampleBufferRef sample = [output_ copyNextSampleBuffer];
  if (sample == nil) {
    [reader_ cancelReading];
    if (![self startReader]) {
      return NO;
    }
    sample = [output_ copyNextSampleBuffer];
  }
  if (sample == nil) {
    return NO;
  }
  if (!pcm_format_verified_) {
    const CMAudioFormatDescriptionRef format = CMSampleBufferGetFormatDescription(sample);
    const AudioStreamBasicDescription* description =
        format == nil ? nullptr : CMAudioFormatDescriptionGetStreamBasicDescription(format);
    const bool valid = description != nullptr && description->mFormatID == kAudioFormatLinearPCM &&
                       static_cast<int>(description->mSampleRate) == sample_rate_ &&
                       description->mChannelsPerFrame == channels_ && description->mBitsPerChannel == 16 &&
                       description->mBytesPerFrame == bytes_per_frame_ &&
                       (description->mFormatFlags & kAudioFormatFlagIsNonInterleaved) == 0;
    if (!valid) {
      CFRelease(sample);
      return NO;
    }
    pcm_format_verified_ = YES;
  }
  CMBlockBufferRef block = CMSampleBufferGetDataBuffer(sample);
  const size_t length = block == nil ? 0 : CMBlockBufferGetDataLength(block);
  OSStatus copy_status = block == nil ? -1 : noErr;
  if (copy_status == noErr && length > 0) {
    NSMutableData* decoded_pcm = [NSMutableData dataWithLength:length];
    copy_status = CMBlockBufferCopyDataBytes(block, 0, length, decoded_pcm.mutableBytes);
    if (copy_status == noErr) {
      [pending_pcm_ appendData:decoded_pcm];
    }
  }
  CFRelease(sample);
  return copy_status == noErr && length > 0;
}

- (NSData*)copyNextPCMFrames:(NSUInteger)frames {
  const NSUInteger required = frames * bytes_per_frame_;
  while (pending_pcm_.length - pending_offset_ < required) {
    if (![self appendNextPCMBuffer]) {
      return nil;
    }
  }
  NSData* result = [pending_pcm_ subdataWithRange:NSMakeRange(pending_offset_, required)];
  pending_offset_ += required;
  if (pending_offset_ == pending_pcm_.length) {
    [pending_pcm_ setLength:0];
    pending_offset_ = 0;
  } else if (pending_offset_ > 65536) {
    [pending_pcm_ replaceBytesInRange:NSMakeRange(0, pending_offset_) withBytes:nullptr length:0];
    pending_offset_ = 0;
  }
  return result;
}

- (int)sampleRate { return sample_rate_; }
- (int)channels { return channels_; }

@end
