#pragma once

#include <cstddef>

namespace beacon {
namespace logging {

inline constexpr std::size_t kDefaultRingBufferCapacity = 5000;
inline constexpr const char* kRedactedValue = "<redacted>";
inline constexpr const char* kAuthorizationHeader = "Authorization";
inline constexpr const char* kAuthorizationPrefix = "Bearer ";

inline constexpr const char* kLevelInfo = "info";
inline constexpr const char* kLevelWarn = "warn";
inline constexpr const char* kLevelError = "error";
inline constexpr const char* kLevelFatal = "fatal";

inline constexpr const char* kModuleArtifact = "artifact";
inline constexpr const char* kArtifactRecorded = "artifact.recorded";
inline constexpr const char* kArtifactScheme = "artifact://";

inline constexpr const char* kSensitiveToken = "token";
inline constexpr const char* kSensitiveAppCert = "app_cert";
inline constexpr const char* kSensitiveAuthorization = "authorization";

}  // namespace logging
}  // namespace beacon
