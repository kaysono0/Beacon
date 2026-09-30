#pragma once

#import <AppKit/AppKit.h>

namespace beacon::mac {

// 在主线程监听 Console 激活；返回的 observer 必须在关闭 Host 前从 Workspace 移除。
inline id ObserveConsoleActivation(NSWindow* window, void (^did_raise)()) {
  const NSInteger original_level = window.level;
  const NSWindowCollectionBehavior original_behavior = window.collectionBehavior;
  void (^follow_application)(NSRunningApplication*) = ^(NSRunningApplication* application) {
    if (application == nil) {
      return;
    }
    const BOOL console_active = [application.bundleIdentifier isEqualToString:@"ai.beacon.MacTestConsole"];
    // 先设置层级：Console 已在前台时，后续新出现的画面也必须能显示在它上面。
    window.level = console_active ? NSFloatingWindowLevel : original_level;
    NSWindowCollectionBehavior behavior = original_behavior;
    if (console_active) {
      behavior |= NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary;
      if (@available(macOS 13.0, *)) {
        behavior |= NSWindowCollectionBehaviorCanJoinAllApplications;
      }
    }
    window.collectionBehavior = behavior;
    if (!console_active || !window.visible || window.miniaturized) {
      return;
    }
    // 保持 Console 的键盘焦点，也不复活已经隐藏的 Host。
    [window orderFrontRegardless];
    if (did_raise != nil) {
      did_raise();
    }
  };
  follow_application(NSWorkspace.sharedWorkspace.frontmostApplication);
  return [NSWorkspace.sharedWorkspace.notificationCenter
      addObserverForName:NSWorkspaceDidActivateApplicationNotification
      object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification* notification) {
        follow_application(notification.userInfo[NSWorkspaceApplicationKey]);
      }];
}

}  // namespace beacon::mac
