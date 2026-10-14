"""API Key 鉴权。

「简单鉴权」的选型：一个固定 API Key 放在请求头里。
它不区分用户身份，只回答「你是否被允许调这个接口」。

为什么不叫真正的认证：真实系统要有用户表、密码哈希、token 签发与过期。
这里刻意从简，重点是把「依赖注入如何承载横切关注点」这件事做对。

放在 core 层意味着：这里只有纯逻辑，不 import fastapi。
好处是它可以直接被单元测试调用，不需要起 HTTP 服务。
"""

import secrets

from paper_manage.core.config import settings


def is_valid_api_key(candidate: str | None) -> bool:
    """比对 API Key。

    用 secrets.compare_digest 而不是 ==：普通的 == 会在第一个不同的字符处
    提前返回，比较耗时随「匹配了多少前缀」变化。攻击者能通过测量响应时间
    一个字符一个字符地把 key 猜出来（时序攻击）。
    compare_digest 无论内容如何都花同样的时间。

    转成 bytes 再比：compare_digest 对 str 只接受纯 ASCII，
    转 bytes 后无论 key 里有什么字符都不会抛错。
    """
    if not candidate:
        return False
    return secrets.compare_digest(candidate.encode(), settings.api_key.encode())
