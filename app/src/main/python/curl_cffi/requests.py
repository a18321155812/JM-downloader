# curl_cffi.requests stub（安卓）
# 仅提供 AsyncSession 类占位，实际下载走 jmcomic 的 requests postman。
# 如果代码真的调用异步接口，会抛出明确的错误。


class AsyncSession:
    """curl_cffi 异步会话 stub——安卓不可用"""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "curl_cffi 在安卓不可用，异步客户端未启用。请使用同步下载。"
        )

    async def get(self, *args, **kwargs):
        raise NotImplementedError("curl_cffi stub: get 不可用")

    async def post(self, *args, **kwargs):
        raise NotImplementedError("curl_cffi stub: post 不可用")

    async def close(self):
        pass
