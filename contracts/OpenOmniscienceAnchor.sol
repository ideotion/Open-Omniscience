// SPDX-License-Identifier: GPL-3.0-only
/*
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * 
 * Copyright (C) 2026 Ideotion
 * 
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 * 
 * For inquiries, contact: open-omniscience@ideotion.com
 */

pragma solidity ^0.8.0;

/**
 * @title OpenOmniscienceAnchor
 * @dev Smart contract for anchoring Open-Omniscience block Merkle roots to Ethereum.
 * 
 * This contract enables decentralized verification of Open-Omniscience articles by
 * storing block Merkle roots on-chain. Each block contains multiple articles, and
 * the Merkle root provides cryptographic proof of all articles in that block.
 * 
 * Per-article verification is achieved through Merkle proofs: a client can verify
 * that a specific article's hash is included in a block's Merkle root, and then
 * verify that the Merkle root was anchored to this contract.
 * 
 * This approach is cost-effective because:
 * - Only block Merkle roots are stored on-chain (not individual articles)
 * - Multiple articles can be verified through a single on-chain anchor
 * - Verification is trustless and decentralized
 */
contract OpenOmniscienceAnchor {
    
    /**
     * @dev Struct to store anchor information
     */
    struct Anchor {
        bytes32 merkleRoot;
        uint256 timestamp;
        uint256 articleCount;
        string metadataCID;
        address indexedBy;
    }
    
    /**
     * @dev Mapping from Merkle root to anchor information
     */
    mapping(bytes32 => Anchor) private _anchors;
    
    /**
     * @dev Mapping from Merkle root to block height (for lookup)
     */
    mapping(bytes32 => uint256) private _blockHeights;
    
    /**
     * @dev Array of all Merkle roots (for enumeration)
     */
    bytes32[] private _merkleRoots;
    
    /**
     * @dev Mapping from Merkle root to its index in _merkleRoots
     */
    mapping(bytes32 => uint256) private _merkleRootIndices;
    
    /**
     * @dev Total number of anchors
     */
    uint256 private _totalAnchors;
    
    /**
     * @dev Event emitted when a new anchor is created
     */
    event AnchorCreated(
        bytes32 indexed merkleRoot,
        uint256 timestamp,
        uint256 articleCount,
        string metadataCID
    );
    
    /**
     * @dev Event emitted when an anchor is updated (should not happen in practice)
     */
    event AnchorUpdated(
        bytes32 indexed merkleRoot,
        uint256 newTimestamp,
        uint256 newArticleCount,
        string newMetadataCID
    );
    
    /**
     * @dev Anchor a new block Merkle root
     * @param merkleRoot The Merkle root hash of the block
     * @param timestamp Unix timestamp when the block was created
     * @param articleCount Number of articles in the block
     * @param metadataCID IPFS CID or other reference to additional metadata
     */
    function anchor(
        bytes32 merkleRoot,
        uint256 timestamp,
        uint256 articleCount,
        string memory metadataCID
    ) external {
        require(merkleRoot != 0, "Merkle root cannot be zero");
        require(timestamp > 0, "Timestamp must be positive");
        
        // Check if this Merkle root has already been anchored
        if (_anchors[merkleRoot].merkleRoot != 0) {
            // Update existing anchor (should be rare)
            _anchors[merkleRoot] = Anchor({
                merkleRoot: merkleRoot,
                timestamp: timestamp,
                articleCount: articleCount,
                metadataCID: metadataCID,
                indexedBy: msg.sender
            });
            
            emit AnchorUpdated(merkleRoot, timestamp, articleCount, metadataCID);
        } else {
            // Create new anchor
            _anchors[merkleRoot] = Anchor({
                merkleRoot: merkleRoot,
                timestamp: timestamp,
                articleCount: articleCount,
                metadataCID: metadataCID,
                indexedBy: msg.sender
            });
            
            _blockHeights[merkleRoot] = _totalAnchors;
            _merkleRoots.push(merkleRoot);
            _merkleRootIndices[merkleRoot] = _merkleRoots.length - 1;
            _totalAnchors++;
            
            emit AnchorCreated(merkleRoot, timestamp, articleCount, metadataCID);
        }
    }
    
    /**
     * @dev Get anchor information by Merkle root
     * @param merkleRoot The Merkle root to look up
     * @return timestamp Unix timestamp of the anchor
     * @return articleCount Number of articles in the block
     * @return metadataCID IPFS CID or other metadata reference
     */
    function getAnchor(
        bytes32 merkleRoot
    ) external view returns (uint256 timestamp, uint256 articleCount, string memory metadataCID) {
        Anchor memory anchor = _anchors[merkleRoot];
        require(anchor.merkleRoot != 0, "Anchor not found");
        
        return (anchor.timestamp, anchor.articleCount, anchor.metadataCID);
    }
    
    /**
     * @dev Check if a Merkle root has been anchored
     * @param merkleRoot The Merkle root to check
     * @return exists True if the Merkle root has been anchored, false otherwise
     */
    function hasAnchor(
        bytes32 merkleRoot
    ) external view returns (bool exists) {
        return _anchors[merkleRoot].merkleRoot != 0;
    }
    
    /**
     * @dev Get the block height for a Merkle root
     * @param merkleRoot The Merkle root to look up
     * @return blockHeight The block height (index) of this anchor
     */
    function getBlockHeight(
        bytes32 merkleRoot
    ) external view returns (uint256 blockHeight) {
        require(_anchors[merkleRoot].merkleRoot != 0, "Anchor not found");
        return _blockHeights[merkleRoot];
    }
    
    /**
     * @dev Get the total number of anchors
     * @return total Total number of anchors stored
     */
    function getTotalAnchors() external view returns (uint256 total) {
        return _totalAnchors;
    }
    
    /**
     * @dev Get a Merkle root by index
     * @param index The index in the _merkleRoots array
     * @return merkleRoot The Merkle root at the given index
     */
    function getMerkleRootByIndex(
        uint256 index
    ) external view returns (bytes32 merkleRoot) {
        require(index < _merkleRoots.length, "Index out of bounds");
        return _merkleRoots[index];
    }
    
    /**
     * @dev Get the address that indexed an anchor
     * @param merkleRoot The Merkle root to look up
     * @return indexedBy The address that created the anchor
     */
    function getIndexedBy(
        bytes32 merkleRoot
    ) external view returns (address indexedBy) {
        require(_anchors[merkleRoot].merkleRoot != 0, "Anchor not found");
        return _anchors[merkleRoot].indexedBy;
    }
    
    /**
     * @dev Batch anchor multiple Merkle roots (for efficiency)
     * @param merkleRoots Array of Merkle roots to anchor
     * @param timestamps Array of timestamps (must match merkleRoots length)
     * @param articleCounts Array of article counts (must match merkleRoots length)
     * @param metadataCIDs Array of metadata CIDs (must match merkleRoots length)
     */
    function batchAnchor(
        bytes32[] memory merkleRoots,
        uint256[] memory timestamps,
        uint256[] memory articleCounts,
        string[] memory metadataCIDs
    ) external {
        require(merkleRoots.length == timestamps.length, "Arrays must have same length");
        require(merkleRoots.length == articleCounts.length, "Arrays must have same length");
        require(merkleRoots.length == metadataCIDs.length, "Arrays must have same length");
        
        for (uint256 i = 0; i < merkleRoots.length; i++) {
            anchor(merkleRoots[i], timestamps[i], articleCounts[i], metadataCIDs[i]);
        }
    }
}
