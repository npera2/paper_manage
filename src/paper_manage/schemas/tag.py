from pydantic import BaseModel, ConfigDict


class TagRead(BaseModel):
    """标签的输出模型。"""

    # from_attributes=True：允许 Pydantic 直接从 ORM 对象的属性取值。
    # 不加这一行，它只认 dict，序列化 Tag 实例时会报 ValidationError。
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
