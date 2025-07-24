import os
import datetime
import uuid as uuid_pkg
from typing import Optional, AsyncGenerator
import logging
from contextlib import asynccontextmanager

from sqlalchemy import Column, TEXT
from sqlalchemy.dialects.postgresql import INET as PG_INET, BIGINT as PG_BIGINT # Ensure these are imported
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine as sqlalchemy_create_async_engine
from sqlmodel import SQLModel, Field

logger_analytics = logging.getLogger("analytics_db")

# Database URL Config 
ANALYTICS_DATABASE_URL = os.getenv("ANALYTICS_DATABASE_URL")
analytics_engine = None

if ANALYTICS_DATABASE_URL:
    try:
        analytics_engine = sqlalchemy_create_async_engine(
            ANALYTICS_DATABASE_URL,
            echo=os.getenv("DEBUG_SQL", "False").lower() == "true",
            pool_pre_ping=True,
            connect_args={"server_settings": {"application_name": "promptman_backend_analytics"}}
        )
        logger_analytics.info(f"Analytics DB Engine configured for URL (ending with): ...{ANALYTICS_DATABASE_URL[-30:]}")
    except Exception as e:
        logger_analytics.error(f"Failed to create analytics DB engine from URL '{ANALYTICS_DATABASE_URL}': {e}")
        analytics_engine = None
else:
    logger_analytics.warning("ANALYTICS_DATABASE_URL not set. Analytics DB features will be disabled.")


async def init_analytics_db():
    if not analytics_engine:
        logger_analytics.warning("Analytics DB engine not available. Skipping table creation.")
        return
    try:
        async with analytics_engine.connect() as conn:
            logger_analytics.info(f"Successfully connected to analytics DB for initial check: ...{ANALYTICS_DATABASE_URL}")
    except Exception as e:
        logger_analytics.error(f"Error during init_analytics_db connecting to '{ANALYTICS_DATABASE_URL}': {e}")


@asynccontextmanager
async def get_analytics_session_context() -> AsyncGenerator[Optional[AsyncSession], None]:
    """Context manager for analytics sessions in background tasks."""
    if not analytics_engine:
        logger_analytics.warning("Analytics engine not available, cannot provide session.")
        yield None
        return
    
    session: Optional[AsyncSession] = None
    try:
        session = AsyncSession(analytics_engine)
        yield session
    except Exception as e:
        logger_analytics.error(f"Error during analytics session context: {e}")
        if session:
            await session.rollback()
        yield None
    finally:
        if session:
            await session.close()

async def get_analytics_session_dependency() -> AsyncGenerator[Optional[AsyncSession], None]:
    """FastAPI dependency for analytics sessions in route handlers."""
    if not analytics_engine:
        logger_analytics.warning("Analytics engine not available. FastAPI dependency cannot provide session.")
        yield None
        return

    session: Optional[AsyncSession] = None
    try:
        session = AsyncSession(analytics_engine)
        yield session
    except Exception as e:
        logger_analytics.error(f"Error creating analytics session for dependency: {e}")
        yield None
    finally:
        if session:
            await session.close()

# 1. Upload Job Analytics 
class UploadJobAnalytics(SQLModel, table=True): # Inherit directly from SQLModel
    __tablename__ = "upload_job_analytics"

    # Common fields - repeated
    id: Optional[int] = Field(default=None, primary_key=True)
    job_uuid: uuid_pkg.UUID = Field(unique=True, index=True, nullable=False)
    job_start_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    job_end_time: Optional[datetime.datetime] = Field(default=None)
    final_status: Optional[str] = Field(default=None, max_length=20, index=True)
    error_message: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    error_type: Optional[str] = Field(default=None, max_length=100, index=True)
    user_ip: Optional[str] = Field(default=None, sa_column=Column(PG_INET))
    user_region: Optional[str] = Field(default=None, max_length=255)
    output_size_bytes: Optional[int] = Field(default=None, sa_column=Column(PG_BIGINT))
    total_processing_duration_seconds: Optional[float] = Field(default=None)

    # Upload-specific fields
    original_folder_name_root: Optional[str] = Field(default=None, max_length=255)
    initial_files_selected_count: Optional[int] = Field(default=None)
    filtered_files_processed_count: Optional[int] = Field(default=None)
    upload_folder_size_bytes: Optional[int] = Field(default=None, sa_column=Column(PG_BIGINT))
    backend_upload_handling_duration_seconds: Optional[float] = Field(default=None)
    code_analysis_duration_seconds: Optional[float] = Field(default=None)


# 2. Repo Job Analytics 
class RepoJobAnalytics(SQLModel, table=True): # Inherit directly from SQLModel
    __tablename__ = "repo_job_analytics"

    # Common fields - repeated
    id: Optional[int] = Field(default=None, primary_key=True)
    job_uuid: uuid_pkg.UUID = Field(unique=True, index=True, nullable=False)
    job_start_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    job_end_time: Optional[datetime.datetime] = Field(default=None)
    final_status: Optional[str] = Field(default=None, max_length=20, index=True)
    error_message: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    error_type: Optional[str] = Field(default=None, max_length=100, index=True)
    user_ip: Optional[str] = Field(default=None, sa_column=Column(PG_INET))
    user_region: Optional[str] = Field(default=None, max_length=255)
    output_size_bytes: Optional[int] = Field(default=None, sa_column=Column(PG_BIGINT))
    total_processing_duration_seconds: Optional[float] = Field(default=None)

    # Repo-specific fields
    repo_url: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    cloned_repo_name: Optional[str] = Field(default=None, max_length=255)
    clone_successful: Optional[bool] = Field(default=None)
    cloned_repo_size_bytes: Optional[int] = Field(default=None, sa_column=Column(PG_BIGINT))
    git_clone_duration_seconds: Optional[float] = Field(default=None)
    code_analysis_duration_seconds: Optional[float] = Field(default=None)


# 3. Website Job Analytics 
class WebsiteJobAnalytics(SQLModel, table=True): # Inherit directly from SQLModel
    __tablename__ = "website_job_analytics"

    # Common fields - repeated
    id: Optional[int] = Field(default=None, primary_key=True)
    job_uuid: uuid_pkg.UUID = Field(unique=True, index=True, nullable=False)
    job_start_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    job_end_time: Optional[datetime.datetime] = Field(default=None)
    final_status: Optional[str] = Field(default=None, max_length=20, index=True)
    error_message: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    error_type: Optional[str] = Field(default=None, max_length=100, index=True)
    user_ip: Optional[str] = Field(default=None, sa_column=Column(PG_INET))
    user_region: Optional[str] = Field(default=None, max_length=255)
    output_size_bytes: Optional[int] = Field(default=None, sa_column=Column(PG_BIGINT))
    total_processing_duration_seconds: Optional[float] = Field(default=None)

    # Website-specific fields
    website_url: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    crawl_max_depth_setting: Optional[int] = Field(default=None)
    crawl_max_pages_setting: Optional[int] = Field(default=None)
    crawl_stay_on_domain_setting: Optional[bool] = Field(default=None)
    crawl_include_patterns_setting: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    crawl_exclude_patterns_setting: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    crawl_keywords_setting: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    pages_actually_crawled_count: Optional[int] = Field(default=None)
    website_crawl_duration_seconds: Optional[float] = Field(default=None)