from minio import Minio
from minio.error import S3Error
from app.core.config import settings
import io
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class StorageService:
    """Service for handling file storage with MinIO/S3."""

    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Ensure the bucket exists."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"Error creating bucket: {e}")
            raise

    async def upload_file(
        self,
        file_data: bytes,
        object_name: str,
        content_type: str = "application/octet-stream"
    ) -> str:
        """
        Upload a file to storage.

        Args:
            file_data: File content as bytes
            object_name: Object name/path in storage
            content_type: MIME type of the file

        Returns:
            Object path in storage
        """
        try:
            file_stream = io.BytesIO(file_data)
            self.client.put_object(
                self.bucket,
                object_name,
                file_stream,
                length=len(file_data),
                content_type=content_type,
            )
            logger.info(f"Uploaded file: {object_name}")
            return f"{self.bucket}/{object_name}"
        except S3Error as e:
            logger.error(f"Error uploading file: {e}")
            raise

    async def download_file(self, object_name: str) -> bytes:
        """
        Download a file from storage.

        Args:
            object_name: Object name/path in storage

        Returns:
            File content as bytes
        """
        try:
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Error downloading file: {e}")
            raise

    async def get_presigned_url(
        self,
        object_name: str,
        expires_in: int = 3600
    ) -> str:
        """
        Get a presigned URL for downloading a file.

        Args:
            object_name: Object name/path in storage
            expires_in: URL expiration time in seconds

        Returns:
            Presigned URL
        """
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=timedelta(seconds=expires_in),
            )
            return url
        except S3Error as e:
            logger.error(f"Error generating presigned URL: {e}")
            raise

    async def delete_file(self, object_name: str) -> bool:
        """
        Delete a file from storage.

        Args:
            object_name: Object name/path in storage

        Returns:
            True if deleted successfully
        """
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.info(f"Deleted file: {object_name}")
            return True
        except S3Error as e:
            logger.error(f"Error deleting file: {e}")
            raise


# Singleton instance
storage_service = StorageService()
