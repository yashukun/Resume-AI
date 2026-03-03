"""
PDF Conversion Service
=======================
Converts DOCX files to PDF using LibreOffice in headless mode.

LibreOffice is installed in the Docker image (libreoffice-writer).
This is more reliable than Python-only converters in a Linux container.
"""

import subprocess
import tempfile
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PDFConverter:
    """Convert DOCX bytes → PDF bytes using LibreOffice headless."""

    def convert(self, docx_bytes: bytes) -> Optional[bytes]:
        """
        Convert DOCX to PDF.

        Args:
            docx_bytes: DOCX file content

        Returns:
            PDF file content as bytes, or None on failure
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "resume.docx")
            pdf_path = os.path.join(tmpdir, "resume.pdf")

            # Write DOCX to temp file
            with open(docx_path, "wb") as f:
                f.write(docx_bytes)

            # Convert with LibreOffice headless
            try:
                result = subprocess.run(
                    [
                        "libreoffice",
                        "--headless",
                        "--convert-to", "pdf",
                        "--outdir", tmpdir,
                        docx_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode != 0:
                    logger.error(
                        f"LibreOffice conversion failed: {result.stderr}"
                    )
                    return None

                if not os.path.exists(pdf_path):
                    logger.error("PDF file not created after conversion")
                    return None

                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                logger.info(
                    f"PDF conversion successful: {len(pdf_bytes)} bytes")
                return pdf_bytes

            except subprocess.TimeoutExpired:
                logger.error("LibreOffice conversion timed out (60s)")
                return None
            except FileNotFoundError:
                logger.error(
                    "LibreOffice not found. Install with: "
                    "apt-get install -y libreoffice-writer"
                )
                return None
            except Exception as e:
                logger.error(f"PDF conversion error: {e}")
                return None

    def is_available(self) -> bool:
        """Check if LibreOffice is installed."""
        try:
            result = subprocess.run(
                ["libreoffice", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


# Singleton
pdf_converter = PDFConverter()
