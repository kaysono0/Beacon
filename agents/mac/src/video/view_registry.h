#pragma once

#include <functional>
#include <map>
#include <string>

namespace beacon::mac {

class ViewRegistry {
 public:
  using HandleResolver = std::function<void*(const std::string&)>;

  void Attach(const std::string& key, void* handle);
  void SetHandleResolver(HandleResolver resolver);
  void Detach(const std::string& key);
  void Clear();
  void RegisterView(const std::string& key, const std::string& handle);
  std::string GetView(const std::string& key) const;
  void* GetHandle(const std::string& key);

 private:
  std::map<std::string, std::string> views_;
  std::map<std::string, void*> handles_;
  HandleResolver handle_resolver_;
};

}  // namespace beacon::mac
