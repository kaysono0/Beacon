#include "mac_real_agent_loopback_helper.h"

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>

#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <sys/select.h>
#include <unistd.h>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"
#include "platform/platform_adapter.h"
#include "rtc/rtc_command_vocabulary.h"

namespace beacon::mac::agent_runtime {

// 环回 helper 是 Agora 真实 1v1 场景的专用夹具（视觉探针绑定、预览、Python token 脚本），
// 火山词表下没有对应 op，因此火山变体只提供同接口的空实现，让 agent bridge 源码无需分叉。
#if !defined(BEACON_MAC_RTC_VENDOR_VOLCENGINE)
namespace {

int64_t NowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

void PumpRunLoopForMs(int ms) {
  NSDate* until = [NSDate dateWithTimeIntervalSinceNow:static_cast<NSTimeInterval>(ms) / 1000.0];
  [[NSRunLoop currentRunLoop] runUntilDate:until];
}

const char* GetEnvOrEmpty(const char* name) {
  const char* value = std::getenv(name);
  return value == nullptr ? "" : value;
}

std::optional<Json::Value> ParseJsonObjectOrString(const Json::Value& value) {
  if (value.isObject()) {
    return value;
  }
  if (!value.isString()) {
    return std::nullopt;
  }
  Json::Value parsed;
  if (!beacon::ParseJson(value.asString(), &parsed) || !parsed.isObject()) {
    return std::nullopt;
  }
  return parsed;
}

std::string MakeInvokeRequest(const std::string& interface_name,
                              const std::string& function_name,
                              const Json::Value& params) {
  Json::Value packet(Json::objectValue);
  packet["common"]["action"] = beacon::protocol::kInvokeRequest;
  packet["common"]["op_id"] = "op-local-" + function_name;
  packet["common"]["timestamp_ms"] = Json::Int64(NowMs());
  packet["data"]["node_id"] = "mac-loopback-helper";
  packet["data"]["sync"] = true;
  Json::Value item(Json::objectValue);
  item["target"]["sdk"] = std::string(beacon::mac::rtc_commands::kSdk);
  item["target"]["interface"] = interface_name;
  item["target"]["class_name"] =
      interface_name == beacon::mac::rtc_commands::kVisualProbeInterface
          ? std::string(beacon::mac::rtc_commands::kVisualProbeClass)
          : std::string(beacon::mac::rtc_commands::kEngineClass);
  item["target"]["function"] = function_name;
  item["params"] = beacon::WriteJson(params);
  item["extra"] = "{}";
  packet["data"]["list"].append(item);
  return beacon::WriteJson(packet);
}

bool ResponseHasCode(const std::string& response, int expected_code) {
  Json::Value root;
  return beacon::ParseJson(response, &root) && root["data"].get("code", -1).asInt() == expected_code;
}

void AttachPreviewView(beacon::mac::PlatformAdapter& adapter) {
  static NSMutableArray<NSWindow*>* preview_windows = nil;
  if (preview_windows == nil) {
    preview_windows = [[NSMutableArray alloc] init];
  }
  NSWindow* window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 240)
                                                 styleMask:NSWindowStyleMaskTitled
                                                   backing:NSBackingStoreBuffered
                                                     defer:NO];
  [window setTitle:@"Beacon Loopback Helper Preview"];
  [window orderFrontRegardless];
  [preview_windows addObject:window];
  adapter.views().Attach("local_preview", (__bridge void*)[window contentView]);
}

std::string PythonRepr(const std::string& value) {
  std::string escaped = "'";
  for (char ch : value) {
    if (ch == '\\' || ch == '\'') {
      escaped.push_back('\\');
    }
    escaped.push_back(ch);
  }
  escaped.push_back('\'');
  return escaped;
}

}  // namespace

std::optional<LoopbackHelperConfig> ExtractLoopbackHelperConfig(const Json::Value& packet) {
  const Json::Value& list = packet["data"]["list"];
  if (!list.isArray()) {
    return std::nullopt;
  }
  for (const Json::Value& item : list) {
    if (item["target"].get("function", "").asString() != std::string(beacon::mac::rtc_commands::kJoinChannel)) {
      continue;
    }
    const auto extra = ParseJsonObjectOrString(item["extra"]);
    if (!extra || extra->get("remote_peer_fixture", "").asString() != "agora_loopback_helper") {
      continue;
    }
    const auto params = ParseJsonObjectOrString(item["params"]);
    if (!params) {
      return std::nullopt;
    }
    LoopbackHelperConfig config;
    config.channel = params->get("channel", "").asString();
    config.token = params->get("token", "").asString();
    config.uid = params->get("uid", 1001).asInt() + 1;
    if (config.channel.empty() || config.token.empty()) {
      return std::nullopt;
    }
    return config;
  }
  return std::nullopt;
}

bool HelperModeEnabled() {
  const char* value = std::getenv("BEACON_LOOPBACK_HELPER_MODE");
  return value != nullptr && value[0] == '1' && value[1] == '\0';
}

int RunLoopbackHelperMode() {
  const std::string channel = GetEnvOrEmpty("BEACON_LOOPBACK_CHANNEL");
  const std::string token = GetEnvOrEmpty("BEACON_LOOPBACK_TOKEN");
  const int uid = std::atoi(GetEnvOrEmpty("BEACON_LOOPBACK_UID"));
  if (channel.empty() || token.empty() || uid <= 0) {
    std::cout << "ERROR missing helper channel/token/uid\n";
    std::cout.flush();
    return 1;
  }

  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  if (adapter.Init() != beacon::kOk || adapter.Bind() != beacon::kOk) {
    std::cout << "ERROR helper adapter init failed\n";
    std::cout.flush();
    return 1;
  }
  AttachPreviewView(adapter);
  adapter.events().SetNodeId("mac-loopback-helper");

  Json::Value setup_params(Json::objectValue);
  setup_params["view_role"] = "local_preview";
  if (!ResponseHasCode(adapter.kernel().HandleRequest(MakeInvokeRequest(
                           std::string(beacon::mac::rtc_commands::kVisualProbeInterface),
                           std::string(beacon::mac::rtc_commands::kBindLocalVideo), setup_params)),
                       beacon::kOk)) {
    std::cout << "ERROR helper bindLocalVideo failed\n";
    std::cout.flush();
    adapter.Destroy();
    return 1;
  }
  if (!ResponseHasCode(adapter.kernel().HandleRequest(MakeInvokeRequest(
                           std::string(beacon::mac::rtc_commands::kPreviewInterface),
                           std::string(beacon::mac::rtc_commands::kStartPreview), Json::Value(Json::objectValue))),
                       beacon::kOk)) {
    std::cout << "ERROR helper startPreview failed\n";
    std::cout.flush();
    adapter.Destroy();
    return 1;
  }

  Json::Value join_params(Json::objectValue);
  join_params["channel"] = channel;
  join_params["uid"] = uid;
  join_params["token"] = token;
  join_params["publish_camera"] = true;
  join_params["publish_microphone"] = true;
  join_params["auto_subscribe_audio"] = true;
  join_params["auto_subscribe_video"] = true;
  if (!ResponseHasCode(adapter.kernel().HandleRequest(MakeInvokeRequest(
                           std::string(beacon::mac::rtc_commands::kInterface),
                           std::string(beacon::mac::rtc_commands::kJoinChannel), join_params)),
                       beacon::kOk)) {
    std::cout << "ERROR helper joinChannel failed\n";
    std::cout.flush();
    adapter.Destroy();
    return 1;
  }

  std::cout << "READY\n";
  std::cout.flush();
  bool input_done = false;
  std::mutex input_mutex;
  std::thread input_thread([&]() {
    std::string ignored;
    while (std::getline(std::cin, ignored)) {
    }
    std::lock_guard<std::mutex> lock(input_mutex);
    input_done = true;
  });
  while (true) {
    {
      std::lock_guard<std::mutex> lock(input_mutex);
      if (input_done) {
        break;
      }
    }
    PumpRunLoopForMs(10);
  }

  adapter.kernel().HandleRequest(MakeInvokeRequest(std::string(beacon::mac::rtc_commands::kInterface),
                                                  std::string(beacon::mac::rtc_commands::kLeaveChannel),
                                                  Json::Value(Json::objectValue)));
  adapter.kernel().HandleRequest(MakeInvokeRequest(std::string(beacon::mac::rtc_commands::kPreviewInterface),
                                                  std::string(beacon::mac::rtc_commands::kStopPreview),
                                                  Json::Value(Json::objectValue)));
  input_thread.join();
  adapter.Destroy();
  return 0;
}

LoopbackHelperManager::LoopbackHelperManager(std::string executable_path) : executable_path_(std::move(executable_path)) {}

LoopbackHelperManager::~LoopbackHelperManager() {
  Stop();
}

bool LoopbackHelperManager::EnsureStarted(const LoopbackHelperConfig& config, std::string* error_message) {
  Stop();
  @autoreleasepool {
    std::string helper_token;
    if (!BuildHelperToken(config.channel, config.uid, &helper_token, error_message)) {
      return false;
    }
    NSTask* task = [[NSTask alloc] init];
    task.launchPath = [NSString stringWithUTF8String:executable_path_.c_str()];
    NSMutableDictionary* environment = [[[NSProcessInfo processInfo] environment] mutableCopy];
    environment[@"BEACON_LOOPBACK_HELPER_MODE"] = @"1";
    environment[@"BEACON_LOOPBACK_CHANNEL"] = [NSString stringWithUTF8String:config.channel.c_str()];
    environment[@"BEACON_LOOPBACK_TOKEN"] = [NSString stringWithUTF8String:helper_token.c_str()];
    environment[@"BEACON_LOOPBACK_UID"] = [NSString stringWithFormat:@"%d", config.uid];
    NSString* helper_home = [NSTemporaryDirectory()
        stringByAppendingPathComponent:[NSString stringWithFormat:@"beacon-loopback-home-%d-%lld",
                                                                 config.uid,
                                                                 static_cast<long long>(NowMs())]];
    NSString* helper_logs = [[helper_home stringByAppendingPathComponent:@"Library"] stringByAppendingPathComponent:@"Logs"];
    [[NSFileManager defaultManager] createDirectoryAtPath:helper_logs withIntermediateDirectories:YES attributes:nil error:nil];
    environment[@"HOME"] = helper_home;
    environment[@"CFFIXED_USER_HOME"] = helper_home;
    task.environment = environment;
    NSPipe* input = [NSPipe pipe];
    NSPipe* output = [NSPipe pipe];
    task.standardInput = input;
    task.standardOutput = output;
    task.standardError = output;
    @try {
      [task launch];
    } @catch (NSException* exception) {
      if (error_message != nullptr) {
        *error_message = std::string("launch helper failed: ") + [[exception reason] UTF8String];
      }
      return false;
    }
    task_ = (__bridge_retained void*)task;
    stdin_pipe_ = (__bridge_retained void*)input;
    stdout_pipe_ = (__bridge_retained void*)output;
    std::string handshake;
    if (!WaitForHandshake(&handshake)) {
      if (error_message != nullptr) {
        *error_message = handshake.empty() ? "helper handshake timeout" : handshake;
      }
      Stop();
      return false;
    }
    return true;
  }
}

void LoopbackHelperManager::Stop() {
  @autoreleasepool {
    if (task_ == nullptr) {
      return;
    }
    NSTask* task = (__bridge_transfer NSTask*)task_;
    NSPipe* input = (__bridge_transfer NSPipe*)stdin_pipe_;
    NSPipe* output = (__bridge_transfer NSPipe*)stdout_pipe_;
    task_ = nullptr;
    stdin_pipe_ = nullptr;
    stdout_pipe_ = nullptr;
    [[input fileHandleForWriting] closeFile];
    for (int i = 0; i < 100 && [task isRunning]; ++i) {
      PumpRunLoopForMs(10);
    }
    if ([task isRunning]) {
      [task terminate];
      [task waitUntilExit];
    }
    (void)output;
  }
}

bool LoopbackHelperManager::BuildHelperToken(const std::string& channel,
                                             int uid,
                                             std::string* token,
                                             std::string* error_message) {
  const char* app_id = std::getenv("AGORA_APP_ID");
  const char* app_cert = std::getenv("AGORA_APP_CERT");
  if (app_id == nullptr || app_id[0] == '\0' || app_cert == nullptr || app_cert[0] == '\0') {
    if (error_message != nullptr) {
      *error_message = "missing AGORA_APP_ID or AGORA_APP_CERT for helper token";
    }
    return false;
  }
  const auto expire_at = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now()) + 3600;
  std::ostringstream script;
  script << "from agora_token_builder import RtcTokenBuilder;"
         << "import os,sys;"
         << "sys.stdout.write(RtcTokenBuilder.buildTokenWithUid("
         << "os.environ['AGORA_APP_ID'], os.environ['AGORA_APP_CERT'], "
         << PythonRepr(channel) << ", " << uid << ", 1, " << expire_at << "))";

  NSPipe* output_pipe = [NSPipe pipe];
  NSTask* task = [[NSTask alloc] init];
  task.launchPath = @"/usr/bin/env";
  task.arguments = @[ @"uv", @"run", @"--python", @"3.11", @"--extra", @"agora", @"python", @"-c", [NSString stringWithUTF8String:script.str().c_str()] ];
  task.currentDirectoryPath = [[[NSFileManager defaultManager] currentDirectoryPath] stringByAppendingPathComponent:@"server"];
  task.standardOutput = output_pipe;
  task.standardError = output_pipe;
  @try {
    [task launch];
  } @catch (NSException* exception) {
    if (error_message != nullptr) {
      *error_message = std::string("launch token builder failed: ") + [[exception reason] UTF8String];
    }
    return false;
  }
  [task waitUntilExit];
  NSData* output_data = [[output_pipe fileHandleForReading] readDataToEndOfFile];
  NSString* output = [[NSString alloc] initWithData:output_data encoding:NSUTF8StringEncoding];
  if (task.terminationStatus != 0 || output == nil || output.length == 0) {
    if (error_message != nullptr) {
      *error_message = output == nil ? "helper token builder failed" : [output UTF8String];
    }
    return false;
  }
  if (token != nullptr) {
    *token = [[output stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] UTF8String];
  }
  return true;
}

bool LoopbackHelperManager::WaitForHandshake(std::string* message) {
  NSPipe* output = (__bridge NSPipe*)stdout_pipe_;
  NSTask* task = (__bridge NSTask*)task_;
  const int fd = [[output fileHandleForReading] fileDescriptor];
  std::string buffer;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
  while (std::chrono::steady_clock::now() < deadline) {
    fd_set read_set;
    FD_ZERO(&read_set);
    FD_SET(fd, &read_set);
    timeval timeout = {.tv_sec = 0, .tv_usec = 100000};
    const int ready = select(fd + 1, &read_set, nullptr, nullptr, &timeout);
    if (ready > 0 && FD_ISSET(fd, &read_set)) {
      char chunk[256];
      const ssize_t size = read(fd, chunk, sizeof(chunk));
      if (size <= 0) {
        break;
      }
      buffer.append(chunk, static_cast<size_t>(size));
      const size_t newline = buffer.find('\n');
      if (newline == std::string::npos) {
        continue;
      }
      const std::string line = buffer.substr(0, newline);
      if (line == "READY") {
        return true;
      }
      if (message != nullptr) {
        *message = line;
      }
      return false;
    }
    if (![task isRunning]) {
      break;
    }
    PumpRunLoopForMs(10);
  }
  if (message != nullptr && message->empty()) {
    *message = buffer;
  }
  return false;
}

#else  // BEACON_MAC_RTC_VENDOR_VOLCENGINE

std::optional<LoopbackHelperConfig> ExtractLoopbackHelperConfig(const Json::Value&) { return std::nullopt; }

bool HelperModeEnabled() { return false; }

int RunLoopbackHelperMode() {
  std::cerr << "loopback helper mode is Agora-only\n";
  return 2;
}

LoopbackHelperManager::LoopbackHelperManager(std::string executable_path) : executable_path_(std::move(executable_path)) {}

LoopbackHelperManager::~LoopbackHelperManager() = default;

bool LoopbackHelperManager::EnsureStarted(const LoopbackHelperConfig&, std::string* error_message) {
  if (error_message != nullptr) {
    *error_message = "loopback helper is Agora-only";
  }
  return false;
}

void LoopbackHelperManager::Stop() {}

#endif  // BEACON_MAC_RTC_VENDOR_VOLCENGINE

}  // namespace beacon::mac::agent_runtime
