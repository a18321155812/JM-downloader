# curl_cffi stub
# 安卓上不可用（libcurl-impersonate 依赖 glibc）。
# jmcomic 的异步客户端才需要它，本 App 使用同步 requests 模式，
# 此 stub 仅用于让 import 通过。
__version__ = "0.0.0-android-stub"
