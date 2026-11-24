from pydantic import BaseModel, Field


class DocumentIngestRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, description="待入库的原始文本列表")
    metadatas: list[dict] | None = Field(
        default=None,
        description="与 texts 一一对应的元数据；可选",
    )
    source: str = Field(default="manual", description="来源标签")


class DocumentIngestResponse(BaseModel):
    ingested_chunks: int
    collection: str
    source: str


class DocumentChunkItem(BaseModel):
    id: int
    content: str
    source: str
    metadata: dict = Field(default_factory=dict)
    embedding_dims: int
    vectorized: bool
    created_at: str | None = None


class DocumentListResponse(BaseModel):
    total_returned: int
    items: list[DocumentChunkItem]


class DocumentSourceStat(BaseModel):
    source: str
    count: int


class DocumentStatsResponse(BaseModel):
    total_chunks: int
    vectorized_chunks: int
    embedding_dims: int
    sources: list[DocumentSourceStat] = Field(default_factory=list)
    collection: str
