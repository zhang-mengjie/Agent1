"""知识库（FAQ）入库与查询的数据结构。"""

from pydantic import (  # Pydantic v2：数据校验与序列化库
    BaseModel,  # 模型基类：子类自动获得字段校验与 JSON 序列化能力
    Field,  # 字段声明：配置默认值、约束与 OpenAPI 描述
)


class DocumentIngestRequest(BaseModel):
    """POST /documents 的请求体：批量文本入库。

    Attributes:
        texts: 待入库文本列表，至少 1 条；每条独立切分后向量化。
        metadatas: 与 texts 一一对应的元数据字典；提供时长度必须与 texts 一致。
        source: 来源标签，如 faq / policy / pdf 文件名，默认 "faq"；会写入每条切片的 metadata。
    """

    texts: list[str] = Field(..., min_length=1, description="待入库文本列表，至少 1 条")
    metadatas: list[dict] | None = Field(default=None, description="与 texts 一一对应的元数据；提供时长度必须一致")
    source: str = Field(default="faq", description="来源标签，如 faq / policy / pdf 文件名")


class DocumentIngestResponse(BaseModel):
    """入库类接口（POST /documents、POST /documents/pdf）的响应体。

    Attributes:
        ingested_chunks: 实际写入 rag_chunks 表的切片数。
        collection: 逻辑集合名（配置 collection_name），仅作标识，真实表名为 rag_chunks。
        source: 本次入库实际使用的来源标签。
    """

    ingested_chunks: int = Field(description="实际写入的切片数")
    collection: str = Field(description="逻辑集合名，真实表名为 rag_chunks")
    source: str = Field(description="本次入库使用的来源标签")


class DocumentChunkItem(BaseModel):
    """GET /documents 返回的单个文本切片。

    Attributes:
        id: 切片主键（rag_chunks.id）。
        content: 切片文本内容。
        source: 来源标签，取自 metadata 的 source 字段，缺失时为 "unknown"。
        metadata: 切片元数据字典，至少含 source 与 doc_index。
        embedding_dims: 该切片向量的维度；未向量化时为 0。
        vectorized: embedding 是否非空。
        created_at: 入库时间 ISO 字符串，可为空。
    """

    id: int = Field(description="切片主键")
    content: str = Field(description="切片文本内容")
    source: str = Field(description="来源标签，取自 metadata.source")
    metadata: dict = Field(default_factory=dict, description="切片元数据字典")
    embedding_dims: int = Field(description="向量维度，未向量化时为 0")
    vectorized: bool = Field(description="embedding 是否非空")
    created_at: str | None = Field(default=None, description="入库时间 ISO 字符串，可为空")


class DocumentListResponse(BaseModel):
    """GET /documents 的响应体。

    Attributes:
        total_returned: 本次返回的切片条数（受 limit 限制，非表内总数）。
        items: 切片列表。
    """

    total_returned: int = Field(description="本次返回条数，非表内总行数")
    items: list[DocumentChunkItem] = Field(description="切片列表")


class DocumentSourceStat(BaseModel):
    """按来源标签分组的切片计数。

    Attributes:
        source: 来源标签。
        count: 该来源下的切片数。
    """

    source: str = Field(description="来源标签")
    count: int = Field(description="该来源的切片数")


class DocumentStatsResponse(BaseModel):
    """GET /documents/stats 的响应体：知识库概况统计。

    Attributes:
        total_chunks: rag_chunks 表切片总数。
        vectorized_chunks: 其中 embedding 非空的切片数。
        embedding_dims: 样本向量维度；空库或未向量化时为 0。
        sources: 按来源分组的切片计数列表。
        collection: 逻辑集合名（配置 collection_name）。
    """

    total_chunks: int = Field(description="切片总数")
    vectorized_chunks: int = Field(description="已向量化（embedding 非空）的切片数")
    embedding_dims: int = Field(description="样本向量维度，空库时为 0")
    sources: list[DocumentSourceStat] = Field(default_factory=list, description="按来源分组的计数")
    collection: str = Field(description="逻辑集合名")
