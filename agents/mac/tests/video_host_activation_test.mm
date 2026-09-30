#import <AppKit/AppKit.h>

#include <iostream>

#include "video/video_host_activation.h"

@interface BeaconActivationTestApplication : NSRunningApplication
@property(nonatomic, copy) NSString* testBundleIdentifier;
@end
@implementation BeaconActivationTestApplication
- (NSString*)bundleIdentifier { return self.testBundleIdentifier; }
@end

@interface BeaconActivationTestWindow : NSWindow
@property(nonatomic) NSUInteger frontRequests;
@end
@implementation BeaconActivationTestWindow
- (void)orderFrontRegardless {
  self.frontRequests += 1;
  [super orderFrontRegardless];
}
@end

namespace {

void PostActivation(NSString* bundle) {
  BeaconActivationTestApplication* application = [BeaconActivationTestApplication new];
  application.testBundleIdentifier = bundle;
  [NSWorkspace.sharedWorkspace.notificationCenter postNotificationName:NSWorkspaceDidActivateApplicationNotification
      object:NSWorkspace.sharedWorkspace userInfo:@{NSWorkspaceApplicationKey: application}];
}

int VerifyActivation(BeaconActivationTestWindow* window) {
  const NSInteger original_level = window.level;
  const NSWindowCollectionBehavior original_behavior = window.collectionBehavior;
  __block NSUInteger raised = 0;
  id observer = beacon::mac::ObserveConsoleActivation(window, ^{ raised += 1; });
  NSNotificationCenter* center = NSWorkspace.sharedWorkspace.notificationCenter;
  PostActivation(@"ai.beacon.MacTestConsole");
  bool hidden_stayed_hidden = !window.visible && raised == 0;
  bool ready_before_show = window.level == NSFloatingWindowLevel &&
      (window.collectionBehavior & NSWindowCollectionBehaviorFullScreenAuxiliary) != 0;
  [window orderFrontRegardless];
  window.frontRequests = 0;
  PostActivation(@"com.apple.finder");
  [center postNotificationName:NSWorkspaceDidActivateApplicationNotification
      object:NSWorkspace.sharedWorkspace userInfo:nil];
  bool ignored_other_apps = window.frontRequests == 0 && raised == 0 &&
      window.level == original_level && window.collectionBehavior == original_behavior;
  const BOOL active_before = NSApp.active;
  NSWindow* key_before = NSApp.keyWindow;
  PostActivation(@"ai.beacon.MacTestConsole");
  bool brought_forward = window.visible && window.frontRequests == 1 && raised == 1;
  bool above_console = window.level == NSFloatingWindowLevel;
  bool preserved_focus = NSApp.active == active_before && NSApp.keyWindow == key_before;
  PostActivation(@"com.apple.finder");
  bool restored_level = window.level == original_level && window.collectionBehavior == original_behavior;
  [center removeObserver:observer];
  PostActivation(@"ai.beacon.MacTestConsole");
  bool observer_removed = window.frontRequests == 1 && raised == 1 && window.level == original_level;
  [window close];
  if (!hidden_stayed_hidden || !ignored_other_apps || !brought_forward || !ready_before_show ||
      !above_console || !restored_level || !preserved_focus || !observer_removed) {
    std::cerr << "BRIDGE-MAC-VIDEO-HOST-ACTIVATION hidden=" << hidden_stayed_hidden
              << " unrelated=" << ignored_other_apps << " raised=" << brought_forward
              << " prepared=" << ready_before_show << " floating=" << above_console
              << " restored=" << restored_level << " focus=" << preserved_focus
              << " removed=" << observer_removed << "\n";
    return 1;
  }
  return 0;
}

}  // namespace

int BridgeMacVideoHostActivation() {
  @autoreleasepool {
    [NSApplication sharedApplication];
    BeaconActivationTestWindow* window = [[BeaconActivationTestWindow alloc]
        initWithContentRect:NSMakeRect(0, 0, 160, 90) styleMask:NSWindowStyleMaskTitled
        backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    return VerifyActivation(window);
  }
}
