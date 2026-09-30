#pragma once

#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>

// 厂商无关的本地 MP4 解码器：只提供循环的像素帧，不参与 RTC SDK 生命周期或推送。
@interface BeaconSyntheticVideoClip : NSObject
- (instancetype)initWithPath:(NSString*)path;
- (CVPixelBufferRef)copyNextFrame CF_RETURNS_RETAINED;
- (int)width;
- (int)height;
@end

// PCM 解码器。仅循环读取指定素材音轨，不参与 RTC SDK 生命周期或推送。
@interface BeaconSyntheticAudioClip : NSObject
- (instancetype)initWithPath:(NSString*)path;
- (NSData*)copyNextPCMFrames:(NSUInteger)frames;
- (int)sampleRate;
- (int)channels;
@end

NSString* BeaconSyntheticVideoClipPath();
NSString* BeaconSyntheticPairedMediaClipPath();
NSString* BeaconSyntheticAudioClipPath();
