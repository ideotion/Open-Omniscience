"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Blockchain API Routes for Open-Omniscience

Provides REST API endpoints for per-article blockchain verification.

Endpoints:
- GET /api/blockchain/verify?article_id=... - Verify a single article
- POST /api/blockchain/verify - Verify with POST body
- GET /api/blockchain/articles/{article_id}/proof - Get Merkle proof for an article
- GET /api/blockchain/anchors - List all block anchors
- GET /api/blockchain/status - Service status

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import json
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Path
from fastapi.responses import JSONResponse

from src.blockchain import get_blockchain_service, BlockchainService
from src.blockchain.core.anchor_service import VerificationResult

# Create router
router = APIRouter(prefix="/api/blockchain", tags=["blockchain"])


def get_service() -> BlockchainService:
    """Get the blockchain service instance."""
    return get_blockchain_service()


@router.get("/status")
async def get_status():
    """
    Get blockchain service status.
    
    Returns:
        Service status including configuration and statistics
    """
    try:
        service = get_service()
        
        # Get statistics
        hash_chain = service.hash_chain
        all_blocks = hash_chain.get_all_blocks()
        
        # Count articles
        cursor = hash_chain.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM article_hashes")
        article_count = cursor.fetchone()[0]
        
        return {
            "status": "running",
            "enabled": service.settings.enabled if service.settings else True,
            "local_chain": {
                "enabled": service.settings.local_chain.enabled if service.settings else True,
                "db_path": str(hash_chain.db_path),
                "articles_per_block": hash_chain.articles_per_block,
                "time_per_block": hash_chain.time_per_block
            },
            "anchoring": {
                "enabled": service.settings.anchoring.enabled if service.settings else True,
                "providers": service.settings.anchoring.providers if service.settings else []
            },
            "statistics": {
                "total_blocks": len(all_blocks),
                "total_articles": article_count,
                "latest_block_height": all_blocks[-1].block_height if all_blocks else 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/verify")
async def verify_article_get(
    article_id: str = Query(..., description="ID of the article to verify"),
    expected_content_hash: Optional[str] = Query(None, description="Expected content hash for verification"),
    expected_metadata_hash: Optional[str] = Query(None, description="Expected metadata hash for verification"),
    expected_source_hash: Optional[str] = Query(None, description="Expected source hash for verification")
):
    """
    Verify a single article (GET version).
    
    Performs per-article verification using Merkle proofs and optional
    blockchain anchoring verification.
    
    Args:
        article_id: The article identifier
        expected_content_hash: Optional expected content hash
        expected_metadata_hash: Optional expected metadata hash
        expected_source_hash: Optional expected source hash
        
    Returns:
        VerificationResult with detailed verification information
    """
    try:
        service = get_service()
        
        result = service.verify_article(
            article_id,
            expected_content_hash=expected_content_hash,
            expected_metadata_hash=expected_metadata_hash,
            expected_source_hash=expected_source_hash
        )
        
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/verify")
async def verify_article_post(request: Dict[str, Any]):
    """
    Verify a single article (POST version).
    
    Accepts a JSON body with article information for verification.
    
    Request body:
    {
        "article_id": "...",
        "expected_content_hash": "...",  // optional
        "expected_metadata_hash": "...", // optional
        "expected_source_hash": "..."    // optional
    }
    
    Returns:
        VerificationResult with detailed verification information
    """
    try:
        article_id = request.get("article_id")
        if not article_id:
            raise HTTPException(status_code=400, detail="article_id is required")
        
        service = get_service()
        
        result = service.verify_article(
            article_id,
            expected_content_hash=request.get("expected_content_hash"),
            expected_metadata_hash=request.get("expected_metadata_hash"),
            expected_source_hash=request.get("expected_source_hash")
        )
        
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/articles/{article_id}/proof")
async def get_article_proof(
    article_id: str = Path(..., description="ID of the article")
):
    """
    Get Merkle proof for an article.
    
    Returns all data needed for a third party to independently verify
    the article using Merkle proofs and block hashes.
    
    Args:
        article_id: The article identifier
        
    Returns:
        Dictionary with hashes, block info, and Merkle proof
    """
    try:
        service = get_service()
        
        data = service.get_article_verification_data(article_id)
        
        if not data:
            raise HTTPException(status_code=404, detail=f"Article {article_id} not found")
        
        return data
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/articles/{article_id}/hashes")
async def get_article_hashes(
    article_id: str = Path(..., description="ID of the article")
):
    """
    Get the 3 hashes for an article.
    
    Returns the content_hash, metadata_hash, and source_hash for an article.
    
    Args:
        article_id: The article identifier
        
    Returns:
        Dictionary with the 3 hashes and block information
    """
    try:
        service = get_service()
        
        hashes = service.hash_chain.get_article_hashes(article_id)
        
        if not hashes:
            raise HTTPException(status_code=404, detail=f"Article {article_id} not found")
        
        return hashes
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/blocks")
async def get_blocks(
    limit: Optional[int] = Query(None, description="Maximum number of blocks to return"),
    block_height: Optional[int] = Query(None, description="Specific block height to retrieve")
):
    """
    Get block information.
    
    Args:
        limit: Maximum number of blocks to return
        block_height: Specific block height to retrieve
        
    Returns:
        List of blocks or a single block
    """
    try:
        service = get_service()
        
        if block_height is not None:
            block = service.hash_chain.get_block(block_height)
            if not block:
                raise HTTPException(status_code=404, detail=f"Block {block_height} not found")
            return block.to_dict()
        else:
            blocks = service.hash_chain.get_all_blocks(limit=limit)
            return [block.to_dict() for block in blocks]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/anchors")
async def get_anchors(
    block_height: Optional[int] = Query(None, description="Filter by block height"),
    provider: Optional[str] = Query(None, description="Filter by provider name")
):
    """
    Get blockchain anchors.
    
    Returns a list of all anchors, optionally filtered by block height or provider.
    
    Args:
        block_height: Optional block height to filter by
        provider: Optional provider name to filter by
        
    Returns:
        List of anchor records
    """
    try:
        service = get_service()
        
        anchors = service.anchor_service.get_anchors(block_height=block_height)
        
        if provider:
            anchors = [a for a in anchors if a.get('provider') == provider]
        
        return anchors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/articles/{article_id}/verify-with-proof")
async def verify_with_proof(
    article_id: str = Path(..., description="ID of the article"),
    request: Dict[str, Any] = None
):
    """
    Verify an article using a provided Merkle proof.
    
    This allows decentralized verification without accessing the local database.
    
    Request body:
    {
        "content_hash": "...",
        "metadata_hash": "...",
        "source_hash": "...",
        "merkle_proof": [...],
        "merkle_root": "..."
    }
    
    Args:
        article_id: The article identifier
        request: Request body with proof data
        
    Returns:
        Verification result
    """
    try:
        if not request:
            raise HTTPException(status_code=400, detail="Request body is required")
        
        content_hash = request.get("content_hash")
        metadata_hash = request.get("metadata_hash")
        source_hash = request.get("source_hash")
        merkle_proof = request.get("merkle_proof")
        merkle_root = request.get("merkle_root")
        
        if not all([content_hash, metadata_hash, source_hash, merkle_proof, merkle_root]):
            raise HTTPException(status_code=400, detail="Missing required fields in request body")
        
        service = get_service()
        
        result = service.verify_article_with_proof(
            article_id,
            content_hash,
            metadata_hash,
            source_hash,
            merkle_proof,
            merkle_root
        )
        
        return {"verified": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/anchor-current-block")
async def anchor_current_block():
    """
    Manually trigger anchoring of the current block.
    
    This endpoint triggers the anchoring of the current block's Merkle root
    to all configured blockchain providers.
    
    Returns:
        Dictionary with anchoring results for each provider
    """
    try:
        service = get_service()
        
        if not service.settings or not service.settings.anchoring.enabled:
            raise HTTPException(status_code=400, detail="Anchoring is disabled")
        
        result = service.anchor_service.anchor_current_block()
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chain-integrity")
async def verify_chain_integrity(
    max_height: Optional[int] = Query(None, description="Maximum block height to verify")
):
    """
    Verify the integrity of the entire block chain.
    
    Checks that each block's previous_hash matches the prior block's block_hash.
    
    Args:
        max_height: Optional maximum block height to verify
        
    Returns:
        Dictionary with verification result
    """
    try:
        service = get_service()
        
        is_valid = service.hash_chain.verify_block_chain_integrity(max_height=max_height)
        
        return {
            "valid": is_valid,
            "max_height_checked": max_height
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Helper function to compute SHA-256 hash (for testing)
def compute_sha256(data: str) -> str:
    """Compute SHA-256 hash of a string."""
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


@router.post("/test/add-article")
async def test_add_article(request: Dict[str, Any]):
    """
    Test endpoint to add an article (for development/testing only).
    
    Request body:
    {
        "article_id": "...",
        "content": "...",
        "metadata": {...},
        "source_url": "..."
    }
    
    Returns:
        Result of adding the article to the blockchain
    """
    try:
        article_id = request.get("article_id")
        content = request.get("content", "")
        metadata = request.get("metadata", {})
        source_url = request.get("source_url", "")
        timestamp = request.get("timestamp", 0)
        
        if not article_id:
            raise HTTPException(status_code=400, detail="article_id is required")
        
        # Compute hashes
        content_hash = compute_sha256(content)
        metadata_hash = compute_sha256(json.dumps(metadata, sort_keys=True))
        source_hash = compute_sha256(f"{source_url}{timestamp}")
        
        service = get_service()
        
        result = service.add_article(
            article_id,
            content_hash,
            metadata_hash,
            source_hash
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
