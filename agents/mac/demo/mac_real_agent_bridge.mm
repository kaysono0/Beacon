#include "platform/platform_adapter.h"

#include <cstdlib>
#include <algorithm>
#include <cmath>
#include <ctime>
#include <future>
#include <functional>
#include <iostream>
#include <memory>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

#include <json/json.h>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"
#include "mac_real_agent_loopback_helper.h"
#include "mac_real_agent_packet_handler.h"
#include "video/video_host_layout.h"
#include "video/video_host_activation.h"
#include "video/video_stats_overlay.h"
#include "mac_real_agent_transport.h"

@interface BeaconVideoTile : NSView
- (void)showOverlayText:(NSString*)text;
@end

@implementation BeaconVideoTile {
  NSTextField* overlay_;
}

- (instancetype)initWithFrame:(NSRect)frame {
  self = [super initWithFrame:frame];
  if (self != nil) {
    overlay_ = [NSTextField labelWithString:@""];
    overlay_.editable = NO;
    overlay_.selectable = NO;
    overlay_.drawsBackground = YES;
    overlay_.backgroundColor = [NSColor colorWithCalibratedWhite:0 alpha:0.72];
    overlay_.textColor = NSColor.whiteColor;
    overlay_.font = [NSFont monospacedSystemFontOfSize:9 weight:NSFontWeightMedium];
    overlay_.lineBreakMode = NSLineBreakByTruncatingMiddle;
    overlay_.maximumNumberOfLines = 4;
    overlay_.hidden = YES;
    [overlay_ setWantsLayer:YES];
    overlay_.layer.zPosition = 1;
    [self addSubview:overlay_];
  }
  return self;
}

- (void)layout {
  [super layout];
  constexpr CGFloat kMargin = 6;
  constexpr CGFloat kOverlayHeight = 58;
  const CGFloat height = std::min(kOverlayHeight, NSHeight(self.bounds));
  overlay_.frame = NSMakeRect(kMargin, NSMaxY(self.bounds) - height - kMargin,
                             std::max<CGFloat>(0, NSWidth(self.bounds) - kMargin * 2), height);
}

- (void)showOverlayText:(NSString*)text {
  if ([overlay_.stringValue isEqualToString:text]) return;
  overlay_.stringValue = text;
  overlay_.hidden = text.length == 0;
}

@end

@interface BeaconVideoTileContainer : NSView
@end

@implementation BeaconVideoTileContainer

- (void)layout {
  [super layout];
  NSMutableArray<NSView*>* visible_tiles = [NSMutableArray array];
  for (NSView* tile in self.subviews) {
    if ([tile isKindOfClass:[BeaconVideoTile class]] && !tile.hidden) {
      [visible_tiles addObject:tile];
    }
  }
  const NSRect bounds = self.bounds;
  if (visible_tiles.count == 1) {
    visible_tiles.firstObject.frame = bounds;
    return;
  }
  const NSUInteger columns = static_cast<NSUInteger>(ceil(sqrt(visible_tiles.count)));
  const NSUInteger rows = static_cast<NSUInteger>(ceil(static_cast<double>(visible_tiles.count) / columns));
  const CGFloat tile_width = std::min(bounds.size.width / columns, bounds.size.height / rows * 16 / 9);
  const CGFloat tile_height = tile_width * 9 / 16;
  const CGFloat grid_width = columns * tile_width;
  const CGFloat grid_height = rows * tile_height;
  const CGFloat left = (bounds.size.width - grid_width) / 2;
  const CGFloat top = (bounds.size.height + grid_height) / 2;
  for (NSUInteger index = 0; index < visible_tiles.count; ++index) {
    const CGFloat x = left + (index % columns) * tile_width;
    const CGFloat y = top - (index / columns + 1) * tile_height;
    visible_tiles[index].frame = NSMakeRect(x, y, tile_width, tile_height);
  }
}

@end

namespace {

using beacon::mac::agent_runtime::AgentPacketHandler;
using beacon::mac::agent_runtime::DirectWebSocketTransport;
using beacon::mac::agent_runtime::LoopbackHelperManager;
using beacon::mac::agent_runtime::TraceStore;

NSWindow* g_video_window = nil;
id g_console_activation_observer = nil;
std::map<std::string, BeaconVideoTile*> g_video_tiles;
std::map<std::string, std::string> g_remote_view_roles;
std::map<std::string, beacon::mac::VideoRenderOverlay> g_video_overlays;
std::string g_current_case_id;
std::string g_local_view_role;
std::mutex g_video_state_mutex;

bool HasVisibleVideoTile() {
  for (const auto& [_, tile] : g_video_tiles) {
    if (tile != nil && !tile.hidden) {
      return true;
    }
  }
  return false;
}

std::string ValueKey(const Json::Value& value) {
  if (value.isString()) return value.asString();
  if (value.isUInt64() || value.isInt64()) return std::to_string(value.asUInt64());
  return "";
}

std::string CurrentOverlayTime() {
  const std::time_t now = std::time(nullptr);
  std::tm local_time{};
  localtime_r(&now, &local_time);
  char buffer[9] = {};
  std::strftime(buffer, sizeof(buffer), "%H:%M:%S", &local_time);
  return buffer;
}

beacon::mac::VideoRenderOverlay NewVideoOverlay(std::string publisher, std::string bitrate_direction) {
  beacon::mac::VideoRenderOverlay overlay;
  overlay.publisher = std::move(publisher);
  overlay.state = "Awaiting first frame";
  overlay.layer = "N/A";
  overlay.bitrate_direction = std::move(bitrate_direction);
  overlay.updated_at = "Not reported";
  return overlay;
}

void ShowVideoOverlay(const std::string& view_role, const beacon::mac::VideoRenderOverlay& overlay);

void UpdateCurrentCaseID(const std::string& case_id) {
  if (case_id.empty()) return;
  std::vector<std::pair<std::string, beacon::mac::VideoRenderOverlay>> snapshots;
  {
    std::lock_guard<std::mutex> lock(g_video_state_mutex);
    if (g_current_case_id == case_id) return;
    g_current_case_id = case_id;
    for (auto& [view_role, overlay] : g_video_overlays) {
      overlay.case_id = case_id;
      snapshots.emplace_back(view_role, overlay);
    }
  }
  for (const auto& [view_role, overlay] : snapshots) ShowVideoOverlay(view_role, overlay);
}

void ShowVideoOverlay(const std::string& view_role, const beacon::mac::VideoRenderOverlay& overlay) {
  BeaconVideoTile* tile = nil;
  {
    std::lock_guard<std::mutex> lock(g_video_state_mutex);
    const auto found = g_video_tiles.find(view_role);
    if (found == g_video_tiles.end()) return;
    tile = found->second;
  }
  const std::string text = beacon::mac::FormatVideoRenderOverlay(overlay);
  dispatch_async(dispatch_get_main_queue(), ^{ [tile showOverlayText:[NSString stringWithUTF8String:text.c_str()]]; });
}

void UpdateVideoOverlay(const std::string& view_role,
                        const std::function<void(beacon::mac::VideoRenderOverlay*)>& update) {
  beacon::mac::VideoRenderOverlay snapshot;
  {
    std::lock_guard<std::mutex> lock(g_video_state_mutex);
    const auto found = g_video_overlays.find(view_role);
    if (found == g_video_overlays.end()) return;
    update(&found->second);
    found->second.updated_at = CurrentOverlayTime();
    snapshot = found->second;
  }
  ShowVideoOverlay(view_role, snapshot);
}

void RegisterVideoOverlay(const std::string& view_role, const std::string& publisher, const std::string& bitrate_direction) {
  if (view_role.empty()) return;
  beacon::mac::VideoRenderOverlay snapshot = NewVideoOverlay(publisher, bitrate_direction);
  {
    std::lock_guard<std::mutex> lock(g_video_state_mutex);
    snapshot.case_id = g_current_case_id;
    g_video_overlays[view_role] = snapshot;
  }
  ShowVideoOverlay(view_role, snapshot);
}

void RecordVideoBindings(const Json::Value& packet) {
  const Json::Value& data = packet["data"];
  UpdateCurrentCaseID(data.get(beacon::protocol::kCaseId, "").asString());
  const Json::Value& calls = data["list"];
  if (!calls.isArray()) return;
  for (const Json::Value& item : calls) {
    const std::string function_name = item["target"].get("function", "").asString();
    Json::Value params;
    if (!beacon::ParseJson(item.get("params", "{}").asString(), &params)) continue;
    const std::string view_role = params.get("view_role", "").asString();
    if (function_name == "bindRemoteVideo") {
      const std::string publisher = ValueKey(params["uid"]);
      if (view_role.empty() || publisher.empty()) continue;
      {
        std::lock_guard<std::mutex> lock(g_video_state_mutex);
        g_remote_view_roles[publisher] = view_role;
      }
      RegisterVideoOverlay(view_role, "Remote uid " + publisher, "RX");
    } else if (function_name == "bindLocalVideo" || function_name == "startPreview") {
      if (view_role.empty()) continue;
      {
        std::lock_guard<std::mutex> lock(g_video_state_mutex);
        g_local_view_role = view_role;
      }
      RegisterVideoOverlay(view_role, "Local preview", "TX");
    } else if (function_name == "startPlayingStream") {
      const std::string stream_id = ValueKey(params["stream_id"]);
      if (view_role.empty() || stream_id.empty()) continue;
      {
        std::lock_guard<std::mutex> lock(g_video_state_mutex);
        g_remote_view_roles[stream_id] = view_role;
      }
      RegisterVideoOverlay(view_role, "Remote stream " + stream_id, "RX");
    } else if (function_name == "releaseView" && !view_role.empty()) {
      UpdateVideoOverlay(view_role, [](beacon::mac::VideoRenderOverlay* overlay) { overlay->state = "Released"; });
    }
  }
}

void UpdateVideoOverlayFromCallback(const std::string& function_name,
                                    const std::string& payload_json,
                                    const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) {
  UpdateCurrentCaseID(origin.case_id);
  Json::Value payload;
  if (!beacon::ParseJson(payload_json, &payload)) return;
  const std::string publisher = ValueKey(payload["uid"]);
  const std::string stream_id = ValueKey(payload["stream_id"]);
  std::string view_role;
  {
    std::lock_guard<std::mutex> lock(g_video_state_mutex);
    const auto by_publisher = g_remote_view_roles.find(publisher);
    const auto by_stream = g_remote_view_roles.find(stream_id);
    if (by_publisher != g_remote_view_roles.end()) view_role = by_publisher->second;
    else if (by_stream != g_remote_view_roles.end()) view_role = by_stream->second;
    else if (function_name == "onLocalVideoStats" || function_name == "onFirstLocalVideoFrame") view_role = g_local_view_role;
  }
  if (view_role.empty()) return;
  UpdateVideoOverlay(view_role, [&](beacon::mac::VideoRenderOverlay* overlay) {
    if (function_name == "onRemoteVideoStats") {
      overlay->state = "Rendering";
      overlay->width = payload.get("width", 0).asInt();
      overlay->height = payload.get("height", 0).asInt();
      overlay->frame_rate = payload.get("renderer_output_frame_rate", 0).asInt();
      overlay->bitrate_direction = "RX";
      overlay->bitrate = payload.get("received_bitrate", 0).asInt();
      if (payload["rx_stream_type"].isInt()) {
        overlay->layer = payload["rx_stream_type"].asInt() == 0 ? "High" :
                         payload["rx_stream_type"].asInt() == 1 ? "Low" : "Unknown";
      }
    } else if (function_name == "onFirstRemoteVideoFrame" || function_name == "onPlayerRenderVideoFirstFrame") {
      overlay->state = "Rendering";
      if (payload.get("width", 0).asInt() > 0) overlay->width = payload["width"].asInt();
      if (payload.get("height", 0).asInt() > 0) overlay->height = payload["height"].asInt();
    } else if (function_name == "onLocalVideoStats") {
      overlay->state = "Rendering";
      if (payload.get("width", 0).asInt() > 0) overlay->width = payload["width"].asInt();
      if (payload.get("height", 0).asInt() > 0) overlay->height = payload["height"].asInt();
      overlay->frame_rate = payload.get("sent_frame_rate", 0).asInt();
      overlay->bitrate_direction = "TX";
      overlay->bitrate = payload.get("sent_bitrate", 0).asInt();
    } else if (function_name == "onFirstLocalVideoFrame") {
      overlay->state = "Rendering";
      overlay->width = payload.get("width", 0).asInt();
      overlay->height = payload.get("height", 0).asInt();
    }
  });
}

class CallbackEventSender {
 public:
  CallbackEventSender(beacon::mac::PlatformAdapter& adapter,
                      DirectWebSocketTransport& transport,
                      AgentPacketHandler& packet_handler)
      : adapter_(&adapter), transport_(&transport), packet_handler_(&packet_handler) {}

  void Send(const std::string& function_name,
            const std::string& payload_json,
            const beacon::CallbackExecutionResult& execution,
            const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_) {
      return;
    }
    std::string send_error;
    if (!transport_->Send(packet_handler_->MakeCallbackEvent(function_name, payload_json, execution, origin),
                          &send_error)) {
      adapter_->kernel().logs().Log("Error", "protocol", "agent.direct.callback_event.send_failed", send_error, 502);
    }
  }

  void Disable() {
    std::lock_guard<std::mutex> lock(mutex_);
    active_ = false;
    adapter_ = nullptr;
    transport_ = nullptr;
    packet_handler_ = nullptr;
  }

 private:
  std::mutex mutex_;
  bool active_ = true;
  beacon::mac::PlatformAdapter* adapter_;
  DirectWebSocketTransport* transport_;
  AgentPacketHandler* packet_handler_;
};

class ObserverReset {
 public:
  ObserverReset(beacon::mac::PlatformAdapter& adapter, std::shared_ptr<CallbackEventSender> sender)
      : adapter_(adapter), sender_(std::move(sender)) {}

  ~ObserverReset() {
    adapter_.events().SetObserver({});
    sender_->Disable();
  }

 private:
  beacon::mac::PlatformAdapter& adapter_;
  std::shared_ptr<CallbackEventSender> sender_;
};

const char* GetEnvOrEmpty(const char* name) {
  const char* value = std::getenv(name);
  return value == nullptr ? "" : value;
}

std::vector<std::string> SplitCsvOrDefault(const char* name, const std::vector<std::string>& fallback) {
  const std::string raw = GetEnvOrEmpty(name);
  if (raw.empty()) {
    return fallback;
  }
  std::vector<std::string> values;
  std::stringstream stream(raw);
  std::string item;
  while (std::getline(stream, item, ',')) {
    if (!item.empty()) {
      values.push_back(item);
    }
  }
  return values.empty() ? fallback : values;
}

// 角色来源是 `BEACON_AGENT_TAGS` 里的 role:<x> tag（与 Server 端 role resolver 同一份事实），
// node_id 约定只作为未打 tag 时的回退，避免各 gate 用不同 node_id 前缀时视图注册不上。
std::string RoleForNode(const std::string& node_id) {
  const std::string prefix = "role:";
  for (const std::string& tag : SplitCsvOrDefault("BEACON_AGENT_TAGS", {})) {
    if (tag.rfind(prefix, 0) == 0) {
      return tag.substr(prefix.size());
    }
  }
  if (node_id == "mac-real-peer-e2e-001") {
    return "peer";
  }
  if (node_id == "mac-real-peer-b-e2e-001") {
    return "peer-b";
  }
  return "primary";
}

NSString* RoleLabelForNode(const std::string& node_id) {
  return [NSString stringWithUTF8String:RoleForNode(node_id).c_str()];
}

std::string LayoutRoleForNode(const std::string& node_id) {
  std::string role = RoleForNode(node_id);
  std::replace(role.begin(), role.end(), '_', '-');
  return role;
}

NSRect WindowFrameForNode(const std::string& node_id) {
  const std::string role = LayoutRoleForNode(node_id);
  NSScreen* screen = [NSScreen mainScreen];
  const NSRect visible = screen == nil ? NSMakeRect(0, 0, 660, 372) : [screen visibleFrame];
  const beacon::mac::VideoHostRect frame = beacon::mac::VideoHostFrameForRole(
      role, {visible.origin.x, visible.origin.y, visible.size.width, visible.size.height});
  return NSMakeRect(frame.x, frame.y, frame.width, frame.height);
}

void AttachAgentViews(beacon::mac::PlatformAdapter& adapter, const std::string& node_id) {
  NSRect frame = WindowFrameForNode(node_id);
  NSString* role_label = RoleLabelForNode(node_id);
  if (g_video_window == nil) {
    g_video_window = [[NSWindow alloc] initWithContentRect:frame
                                                 styleMask:NSWindowStyleMaskTitled
                                                   backing:NSBackingStoreBuffered
                                                     defer:NO];
    BeaconVideoTileContainer* content_view =
        [[BeaconVideoTileContainer alloc] initWithFrame:NSMakeRect(0, 0, frame.size.width, frame.size.height)];
    [content_view setAutoresizingMask:NSViewWidthSizable | NSViewHeightSizable];
    [content_view setWantsLayer:YES];
    content_view.layer.backgroundColor = [[NSColor colorWithCalibratedWhite:0.94 alpha:1.0] CGColor];
    [g_video_window setContentView:content_view];
  }
  [g_video_window setTitle:[NSString stringWithFormat:@"Beacon Video Host (%@)", role_label]];
  if (g_console_activation_observer == nil) {
    g_console_activation_observer = beacon::mac::ObserveConsoleActivation(g_video_window, ^{
      adapter.kernel().logs().Log("Info", "video_host", "video_host.console.activated",
                                  "visible video host brought forward");
    });
  }
  adapter.views().SetHandleResolver([&adapter](const std::string& view_role) -> void* {
    if (view_role.empty() || g_video_window == nil) {
      return nullptr;
    }
    __block BeaconVideoTile* tile = nil;
    void (^ensure_tile)(void) = ^{
      auto existing = g_video_tiles.find(view_role);
      if (existing != g_video_tiles.end()) {
        tile = existing->second;
        return;
      }
      tile = [[BeaconVideoTile alloc] initWithFrame:NSZeroRect];
      [tile setAutoresizingMask:NSViewWidthSizable | NSViewHeightSizable];
      [tile setWantsLayer:YES];
      tile.layer.backgroundColor = [[NSColor colorWithCalibratedWhite:0.9 alpha:1.0] CGColor];
      [tile setHidden:YES];
      [[g_video_window contentView] addSubview:tile];
      g_video_tiles[view_role] = tile;
      adapter.views().Attach(view_role, (__bridge void*)tile);
    };
    if (NSThread.isMainThread) {
      ensure_tile();
    } else {
      dispatch_sync(dispatch_get_main_queue(), ensure_tile);
    }
    beacon::mac::VideoRenderOverlay overlay;
    bool has_overlay = false;
    {
      std::lock_guard<std::mutex> lock(g_video_state_mutex);
      const auto found = g_video_overlays.find(view_role);
      if (found != g_video_overlays.end()) {
        overlay = found->second;
        has_overlay = true;
      }
    }
    if (has_overlay) {
      ShowVideoOverlay(view_role, overlay);
    }
    return (__bridge void*)tile;
  });
  adapter.video_host().SetHandlers(
      [](const beacon::CallData&) {
        if (g_video_window == nil || !HasVisibleVideoTile()) {
          return beacon::CallResult{409, "no active video tile", "{}"};
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [g_video_window orderFrontRegardless]; });
        return beacon::CallResult{beacon::kOk, "video host shown", "{\"visible\":true}"};
      },
      [](const beacon::CallData&) {
        if (g_video_window == nil) {
          return beacon::CallResult{409, "video host is unavailable", "{}"};
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [g_video_window orderOut:nil]; });
        return beacon::CallResult{beacon::kOk, "video host hidden", "{\"visible\":false}"};
      },
      [](const beacon::CallData&) {
        if (g_video_window == nil) {
          return beacon::CallResult{409, "video host is unavailable", "{}"};
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [g_video_window makeKeyAndOrderFront:nil]; });
        return beacon::CallResult{beacon::kOk, "video host focused", "{\"focused\":true}"};
      },
      [node_id](const beacon::CallData&) {
        if (g_video_window == nil) {
          return beacon::CallResult{409, "video host is unavailable", "{}"};
        }
        const NSRect frame = WindowFrameForNode(node_id);
        dispatch_async(dispatch_get_main_queue(), ^{ [g_video_window setFrame:frame display:NO]; });
        return beacon::CallResult{beacon::kOk, "video host rearranged", "{\"rearranged\":true}"};
      });
}

void CloseAgentViews() {
  [NSWorkspace.sharedWorkspace.notificationCenter removeObserver:g_console_activation_observer];
  g_console_activation_observer = nil;
  [g_video_window close];
  g_video_window = nil;
  std::lock_guard<std::mutex> lock(g_video_state_mutex);
  g_video_tiles.clear();
  g_remote_view_roles.clear();
  g_video_overlays.clear();
  g_current_case_id.clear();
  g_local_view_role.clear();
}

int RunDirectAgent(beacon::mac::PlatformAdapter& adapter,
                   LoopbackHelperManager& helper_manager,
                   const std::string& node_id) {
  const std::string ws_url = GetEnvOrEmpty("BEACON_AGENT_WS_URL");
  if (ws_url.empty()) {
    std::cerr << "agent missing BEACON_AGENT_WS_URL\n";
    return 1;
  }

  DirectWebSocketTransport transport;
  std::string error_message;
  if (!transport.Connect(ws_url, &error_message)) {
    adapter.kernel().logs().Log("Error", "link", "agent.direct.connect.failed", error_message, 500);
    std::cerr << "agent websocket connect failed: " << error_message << "\n";
    return 1;
  }
  adapter.kernel().logs().Log("Info", "link", "agent.direct.connect.succeeded", "direct websocket connected");

  const std::string register_packet = beacon::mac::agent_runtime::MakeRegisterPacket(
      node_id,
      GetEnvOrEmpty("BEACON_AGENT_GROUP_ID"),
      SplitCsvOrDefault("BEACON_AGENT_TAGS", {"direct-mock"}),
      SplitCsvOrDefault("BEACON_AGENT_CAPABILITIES", {"rtc.mock"}));
  if (!transport.Send(register_packet, &error_message)) {
    adapter.kernel().logs().Log("Error", "protocol", "agent.direct.register.send_failed", error_message, 502);
    std::cerr << "agent register send failed: " << error_message << "\n";
    return 1;
  }
  std::string register_response;
  if (!transport.Receive(&register_response, &error_message)) {
    adapter.kernel().logs().Log("Error", "protocol", "agent.direct.register.receive_failed", error_message, 408);
    std::cerr << "agent register receive failed: " << error_message << "\n";
    return 1;
  }
  Json::Value register_result;
  if (!beacon::ParseJson(register_response, &register_result) || register_result["data"].get("code", -1).asInt() != 0) {
    adapter.kernel().logs().Log("Error", "protocol", "agent.direct.register.rejected", "registerResponse rejected", 400);
    std::cerr << "agent register rejected\n";
    return 1;
  }

  TraceStore trace_store;
  AgentPacketHandler packet_handler(adapter, trace_store, helper_manager, node_id);
  auto callback_sender = std::make_shared<CallbackEventSender>(adapter, transport, packet_handler);
  adapter.events().SetObserver([callback_sender](const std::string& function_name,
                                                  const std::string& payload_json,
                                                  const beacon::CallbackExecutionResult& execution,
                                                  const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) {
    UpdateVideoOverlayFromCallback(function_name, payload_json, origin);
    callback_sender->Send(function_name, payload_json, execution, origin);
  });
  ObserverReset observer_reset(adapter, callback_sender);

  while (true) {
    std::string message;
    if (!transport.Receive(&message, &error_message)) {
      adapter.kernel().logs().Log("Info", "link", "agent.direct.receive.closed", error_message);
      break;
    }
    Json::Value packet;
    if (!beacon::ParseJson(message, &packet)) {
      continue;
    }
    RecordVideoBindings(packet);
    const std::string action = packet["common"].get("action", "").asString();
    if (action != beacon::protocol::kInvokeRequest && action != beacon::protocol::kCallbackRequest) {
      continue;
    }
    const std::string response = packet_handler.Handle(message, [&](const std::string& event_json) {
      std::string send_error;
      if (!transport.Send(event_json, &send_error)) {
        adapter.kernel().logs().Log("Error", "protocol", "agent.direct.synthetic_event.send_failed", send_error, 502);
      }
    });
    if (!response.empty() && !transport.Send(response, &error_message)) {
      adapter.kernel().logs().Log("Error", "protocol", "agent.direct.response.send_failed", error_message, 502);
      return 1;
    }
  }
  transport.Close();
  adapter.kernel().logs().Log("Info", "link", "agent.direct.shutdown", "direct websocket closed");
  return 0;
}

}  // namespace

int main() {
  if (beacon::mac::agent_runtime::HelperModeEnabled()) {
    return beacon::mac::agent_runtime::RunLoopbackHelperMode();
  }

  const std::string executable_path = [NSProcessInfo processInfo].arguments.count > 0
                                          ? [[[NSProcessInfo processInfo] arguments][0] UTF8String]
                                          : "";
  const std::string node_id = std::string(GetEnvOrEmpty("BEACON_NODE_ID")).empty()
                                  ? "mac-real-e2e-001"
                                  : GetEnvOrEmpty("BEACON_NODE_ID");

  [NSApplication sharedApplication];

  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  if (adapter.Init() != beacon::kOk || adapter.Bind() != beacon::kOk) {
    std::cerr << "agent init failed\n";
    return 1;
  }
  AttachAgentViews(adapter, node_id);
  adapter.events().SetNodeId(node_id);

  LoopbackHelperManager helper_manager(executable_path);
  auto exit_code_promise = std::make_shared<std::promise<int>>();
  std::future<int> exit_code_future = exit_code_promise->get_future();
  beacon::mac::PlatformAdapter* adapter_ptr = &adapter;
  LoopbackHelperManager* helper_manager_ptr = &helper_manager;
  dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
    @autoreleasepool {
      exit_code_promise->set_value(RunDirectAgent(*adapter_ptr, *helper_manager_ptr, node_id));
      dispatch_async(dispatch_get_main_queue(), ^{
        [NSApp stop:nil];
        [NSApp postEvent:[NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                            location:NSZeroPoint
                                       modifierFlags:0
                                           timestamp:0
                                        windowNumber:0
                                             context:nil
                                             subtype:0
                                               data1:0
                                               data2:0]
                atStart:NO];
      });
    }
  });
  [NSApp run];
  const int exit_code = exit_code_future.get();
  helper_manager.Stop();
  adapter.Destroy();
  CloseAgentViews();
  return exit_code;
}
