#include "mac_real_agent_transport.h"

#include <chrono>
#include <mutex>

#import <Foundation/Foundation.h>

namespace beacon::mac::agent_runtime {
namespace {

void PumpRunLoopForMs(int ms) {
  NSDate* until = [NSDate dateWithTimeIntervalSinceNow:static_cast<NSTimeInterval>(ms) / 1000.0];
  [[NSRunLoop currentRunLoop] runUntilDate:until];
}

}  // namespace

class DirectWebSocketTransport::Impl {
 public:
  NSURLSession* session = nil;
  NSURLSessionWebSocketTask* task = nil;
  std::mutex send_mutex;
};

DirectWebSocketTransport::DirectWebSocketTransport() : impl_(std::make_unique<Impl>()) {}

DirectWebSocketTransport::~DirectWebSocketTransport() {
  Close();
}

bool DirectWebSocketTransport::Connect(const std::string& url, std::string* error_message) {
  @autoreleasepool {
    NSURL* ns_url = [NSURL URLWithString:[NSString stringWithUTF8String:url.c_str()]];
    if (ns_url == nil) {
      if (error_message != nullptr) {
        *error_message = "invalid BEACON_AGENT_WS_URL";
      }
      return false;
    }
    impl_->session = [NSURLSession sessionWithConfiguration:[NSURLSessionConfiguration defaultSessionConfiguration]];
    impl_->task = [impl_->session webSocketTaskWithURL:ns_url];
    [impl_->task resume];
    return true;
  }
}

bool DirectWebSocketTransport::Send(const std::string& text, std::string* error_message) {
  std::lock_guard<std::mutex> lock(impl_->send_mutex);
  if (impl_->task == nil) {
    if (error_message != nullptr) {
      *error_message = "websocket is not connected";
    }
    return false;
  }
  __block NSError* send_error = nil;
  dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
  NSString* message = [NSString stringWithUTF8String:text.c_str()];
  NSURLSessionWebSocketMessage* ws_message = [[NSURLSessionWebSocketMessage alloc] initWithString:message];
  [impl_->task sendMessage:ws_message
         completionHandler:^(NSError* error) {
           send_error = error;
           dispatch_semaphore_signal(semaphore);
         }];
  const long wait_result = dispatch_semaphore_wait(semaphore, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC));
  if (wait_result != 0) {
    if (error_message != nullptr) {
      *error_message = "websocket send timeout";
    }
    return false;
  }
  if (send_error != nil) {
    if (error_message != nullptr) {
      *error_message = [[send_error localizedDescription] UTF8String];
    }
    return false;
  }
  return true;
}

bool DirectWebSocketTransport::Receive(std::string* text, std::string* error_message) {
  if (impl_->task == nil) {
    if (error_message != nullptr) {
      *error_message = "websocket is not connected";
    }
    return false;
  }
  __block NSString* received = nil;
  __block NSError* receive_error = nil;
  dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
  [impl_->task receiveMessageWithCompletionHandler:^(NSURLSessionWebSocketMessage* message, NSError* error) {
    receive_error = error;
    if (message.type == NSURLSessionWebSocketMessageTypeString) {
      received = message.string;
    }
    dispatch_semaphore_signal(semaphore);
  }];
  while (dispatch_semaphore_wait(semaphore, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_MSEC)) != 0) {
    PumpRunLoopForMs(10);
  }
  if (receive_error != nil) {
    if (error_message != nullptr) {
      *error_message = [[receive_error localizedDescription] UTF8String];
    }
    return false;
  }
  if (received == nil) {
    if (error_message != nullptr) {
      *error_message = "websocket received non-string message";
    }
    return false;
  }
  if (text != nullptr) {
    *text = [received UTF8String];
  }
  return true;
}

void DirectWebSocketTransport::Close() {
  if (impl_->task != nil) {
    [impl_->task cancelWithCloseCode:NSURLSessionWebSocketCloseCodeNormalClosure reason:nil];
    impl_->task = nil;
  }
  if (impl_->session != nil) {
    [impl_->session invalidateAndCancel];
    impl_->session = nil;
  }
}

}  // namespace beacon::mac::agent_runtime
