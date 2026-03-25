# main.py
"""FastAPI application entry point.

Thin layer: validates input, delegates to Pipeline, returns output.
No business logic lives here.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from customer_support.core.config import settings
from customer_support.pipeline import Pipeline, PipelineResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_pipeline_instance: Pipeline | None = None


def get_pipeline() -> Pipeline:
    """Return the singleton Pipeline instance, constructing it on first call.

    Uses OpenAILLMClient and OpenAIEmbeddingClient when OPENAI_API_KEY is set.
    Falls back to DummyClients for local development without credentials.
    """
    global _pipeline_instance
    if _pipeline_instance is None:
        if settings.openai_api_key:
            from customer_support.retrieval.retriever import FAISSRetriever  # noqa: PLC0415
            from customer_support.services.client import (  # noqa: PLC0415
                OpenAIEmbeddingClient,
                OpenAILLMClient,
            )

            llm_client = OpenAILLMClient()
            embedding_client = OpenAIEmbeddingClient()
            retriever = FAISSRetriever(
                embedding_client=embedding_client,
                vector_db_path=settings.vector_db_path,
            )
            _pipeline_instance = Pipeline(
                llm_client=llm_client,
                embedding_client=embedding_client,
                retriever=retriever,
            )
            logger.info("Pipeline initialised with OpenAI clients")
        else:
            _pipeline_instance = Pipeline()
            logger.warning("No OPENAI_API_KEY found — running with DummyClients")
    return _pipeline_instance


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialise pipeline on startup."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    get_pipeline()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    """API request schema."""

    query: str = Field(..., min_length=10, max_length=1000)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "running", "service": settings.app_name}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/process", response_model=PipelineResult)
async def process_query(request: QueryRequest) -> dict[str, object]:
    """Process a customer query through the full pipeline."""
    pipeline = get_pipeline()
    result = pipeline.process(request.query)
    return result.model_dump()