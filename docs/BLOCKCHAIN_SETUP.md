# Blockchain Verification Setup Guide

**Open Omniscience - Per-Article Blockchain Verification System**

---

## 📖 Overview

This guide will help you set up and configure the blockchain verification system for Open Omniscience. The system provides **per-article cryptographic verification** with optional blockchain anchoring.

---

## 🎯 Prerequisites

### System Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **Python** | 3.8+ | Required for all components |
| **SQLite** | Built into Python | Required for local hash chain |
| **Disk Space** | 100+ MB | For blockchain database |
| **Memory** | 512+ MB | For Merkle tree operations |

### Optional Dependencies (for blockchain anchoring)

| Provider | Package | Installation | Notes |
|----------|---------|--------------|-------|
| **Ethereum** | web3 | `pip install web3` | Requires Ethereum node |
| **IPFS** | ipfshttpclient | `pip install ipfshttpclient` | Requires IPFS node |
| **Arweave** | arweave-python | `pip install arweave-python` | Requires Arweave wallet |

---

## 🚀 Quick Start

### 1. Install Open Omniscience

Follow the main installation guide:

```bash
# For Debian 13 (recommended)
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash

# Or manual installation
pip install -r requirements.txt
```

### 2. Configure Blockchain

Edit the blockchain configuration file:

```bash
nano configs/blockchain.yml
```

Basic configuration:

```yaml
blockchain:
  enabled: true
  local_chain:
    enabled: true
    db_path: "data/blockchain/local_hash_chain.db"
    articles_per_block: 100
    time_per_block: 86400  # 24 hours
  anchoring:
    enabled: false  # Disable for now
    providers: []
```

### 3. Start Open Omniscience

```bash
python -m src.api.main
```

The blockchain module will automatically:
- Create the local hash chain database
- Add articles to the blockchain as they are ingested
- Enable per-article verification

### 4. Verify It's Working

```bash
# Check service status
curl "http://localhost:8000/api/blockchain/status"

# Should return:
# {"status": "running", "enabled": true, ...}
```

---

## 📝 Detailed Configuration

### Configuration File: `configs/blockchain.yml`

```yaml
blockchain:
  # Enable/disable the entire blockchain module
  enabled: true

  # Local Hash Chain Settings
  local_chain:
    enabled: true
    
    # Path to SQLite database
    # Default: data/blockchain/local_hash_chain.db
    db_path: "data/blockchain/local_hash_chain.db"
    
    # Maximum articles per block
    # When a block reaches this limit, a new block is created
    # Default: 100
    articles_per_block: 100
    
    # Maximum time (in seconds) per block
    # When a block reaches this age, a new block is created
    # Default: 86400 (24 hours)
    time_per_block: 86400

  # Blockchain Anchoring Settings
  anchoring:
    # Enable/disable blockchain anchoring
    enabled: true
    
    # Interval (in seconds) between automatic anchoring attempts
    # Default: 86400 (24 hours)
    interval: 86400
    
    # List of providers to use for anchoring
    # Available: local, ethereum, ipfs, arweave
    providers:
      - local
      # - ethereum
      # - ipfs
      # - arweave
    
    # Ethereum-specific settings
    ethereum:
      # Address of the deployed OpenOmniscienceAnchor contract
      contract_address: "0x1234567890123456789012345678901234567890"
      
      # Ethereum node RPC URL
      # Can be local node or Infura/Alchemy
      rpc_url: "http://localhost:8545"
      
      # Private key for signing transactions
      # RECOMMENDED: Set via environment variable instead
      # private_key: "0x..."
      
      # Gas settings
      gas_limit: 200000
      gas_price: 20000000000  # 20 Gwei
    
    # IPFS-specific settings
    ipfs:
      # IPFS node host
      host: "localhost"
      
      # IPFS node API port
      port: 5001
      
      # Use HTTPS instead of HTTP
      use_https: false
    
    # Arweave-specific settings
    arweave:
      # Path to Arweave wallet file
      wallet_path: "~/.arweave/wallet.json"
      
      # Wallet key data (JSON string)
      # RECOMMENDED: Set via environment variable instead
      # wallet_key: "..."
      
      # Arweave node URL
      arweave_url: "https://arweave.net"
```

---

## 🔧 Provider Setup

### Local Provider (Always Available)

The local provider is **always available** and requires no additional setup. It stores anchors in a SQLite database for offline verification.

**Database Location**: `data/blockchain/anchors.db` (created automatically)

### Ethereum Provider

#### 1. Install Dependencies

```bash
pip install web3
```

#### 2. Set Up Ethereum Node

You need access to an Ethereum node. Options:

**Option A: Local Node (Recommended for development)**

```bash
# Install Geth (Go Ethereum)
# https://geth.ethereum.org/docs/install-and-build/install

# Start a local node
geth --syncmode snap --http --http.api eth,net,web3
```

**Option B: Infura (Cloud provider)**

Sign up at [Infura](https://infura.io/) and get your RPC URL.

**Option C: Alchemy (Cloud provider)**

Sign up at [Alchemy](https://www.alchemy.com/) and get your RPC URL.

#### 3. Deploy Smart Contract

The smart contract is located at: `contracts/OpenOmniscienceAnchor.sol`

**Using Remix IDE (Easiest)**

1. Go to [Remix IDE](https://remix.ethereum.org/)
2. Create a new file and paste the contract code
3. Compile the contract
4. Deploy to your chosen network (Injected Web3, Injected Provider, or Web3 Provider)
5. Copy the contract address

**Using Hardhat**

1. Install Hardhat:
   ```bash
   npm install --save-dev hardhat
   ```

2. Create `hardhat.config.js`:
   ```javascript
   require("@nomicfoundation/hardhat-toolbox");
   
   module.exports = {
     solidity: "0.8.0",
     networks: {
       local: {
         url: "http://localhost:8545"
       }
     }
   };
   ```

3. Deploy the contract:
   ```bash
   npx hardhat compile
   npx hardhat run scripts/deploy.js --network local
   ```

4. Copy the deployed contract address

#### 4. Configure Open Omniscience

Update `configs/blockchain.yml`:

```yaml
anchoring:
  enabled: true
  providers:
    - local
    - ethereum
  ethereum:
    contract_address: "0xYOUR_CONTRACT_ADDRESS"
    rpc_url: "http://localhost:8545"
    # private_key: "0xYOUR_PRIVATE_KEY"  # Set via environment variable
    gas_limit: 200000
    gas_price: 20000000000
```

#### 5. (Recommended) Set Private Key via Environment Variable

```bash
# Add to your .env file
export BLOCKCHAIN_ETHEREUM_PRIVATE_KEY="0xyour_private_key"

# Or set in your shell
BLOCKCHAIN_ETHEREUM_PRIVATE_KEY="0xyour_private_key"
```

Then modify the Ethereum provider to read from environment variable.

#### 6. Get Test ETH (For Testnets)

- **Goerli**: [Goerli Faucet](https://goerlifaucet.com/)
- **Sepolia**: [Sepolia Faucet](https://sepoliafaucet.com/)
- **Local**: Use a local testnet with pre-funded accounts

### IPFS Provider

#### 1. Install Dependencies

```bash
pip install ipfshttpclient
```

#### 2. Install and Run IPFS

**Linux/macOS:**

```bash
# Download IPFS
wget https://dist.ipfs.tech/kubo/v0.22.0/kubo_v0.22.0_linux-amd64.tar.gz
 tar -xvzf kubo_v0.22.0_linux-amd64.tar.gz
 cd kubo
 sudo ./install.sh

# Initialize IPFS
ipfs init

# Start IPFS daemon
ipfs daemon
```

**Windows:**

Download from [IPFS Distributions](https://dist.ipfs.tech/#kubo) and follow the installer.

#### 3. Configure Open Omniscience

Update `configs/blockchain.yml`:

```yaml
anchoring:
  enabled: true
  providers:
    - local
    - ipfs
  ipfs:
    host: "localhost"
    port: 5001
    use_https: false
```

#### 4. Test IPFS Connection

```bash
# Check if IPFS is running
ipfs id

# Should return your node ID and information
```

### Arweave Provider

#### 1. Install Dependencies

```bash
pip install arweave-python
```

#### 2. Set Up Arweave Wallet

1. Go to [Arweave Wallet](https://www.arweave.org/wallet)
2. Create a new wallet or import existing
3. Download the wallet JSON file
4. Save it to `~/.arweave/wallet.json`

#### 3. Get AR Tokens

You need AR tokens for transaction fees:

- **Mainnet**: Buy from [exchange](https://www.coingecko.com/en/coins/arweave)
- **Testnet**: Get from [Arweave Testnet Faucet](https://faucet.testnet.arweave.dev/)

#### 4. Configure Open Omniscience

Update `configs/blockchain.yml`:

```yaml
anchoring:
  enabled: true
  providers:
    - local
    - arweave
  arweave:
    wallet_path: "~/.arweave/wallet.json"
    arweave_url: "https://arweave.net"
```

#### 5. (Recommended) Set Wallet Key via Environment Variable

```bash
# Add to your .env file
export BLOCKCHAIN_ARWEAVE_WALLET_KEY='{"kty":"RSA",...}'

# Or set in your shell
BLOCKCHAIN_ARWEAVE_WALLET_KEY='{"kty":"RSA",...}'
```

---

## 🏃 Running the System

### Start Open Omniscience

```bash
python -m src.api.main
```

The service will start on `http://localhost:8000`

### Check Blockchain Status

```bash
curl "http://localhost:8000/api/blockchain/status"
```

### Test Article Ingestion and Verification

```bash
# This will be done automatically as articles are ingested
# You can also manually add articles for testing

# Add a test article (using the test endpoint)
curl -X POST "http://localhost:8000/api/blockchain/test/add-article" \
  -H "Content-Type: application/json" \
  -d '{
    "article_id": "test_article_1",
    "content": "This is test content",
    "metadata": {"source": "test"},
    "source_url": "http://example.com/test"
  }'

# Verify the article
curl "http://localhost:8000/api/blockchain/verify?article_id=test_article_1"

# Get the Merkle proof
curl "http://localhost:8000/api/blockchain/articles/test_article_1/proof"
```

---

## 🔄 Automatic Anchoring

By default, the system does **not** automatically anchor blocks to public blockchains. You have two options:

### Option 1: Manual Anchoring

Trigger anchoring manually via API:

```bash
curl -X POST "http://localhost:8000/api/blockchain/anchor-current-block"
```

### Option 2: Scheduled Anchoring (Recommended)

Set up a cron job or scheduled task to anchor periodically:

**Using cron (Linux/macOS):**

```bash
# Edit crontab
crontab -e

# Add this line to anchor every 24 hours
0 0 * * * curl -X POST "http://localhost:8000/api/blockchain/anchor-current-block" > /dev/null 2>&1
```

**Using systemd timer:**

1. Create service file `/etc/systemd/system/blockchain-anchor.service`:
   ```ini
   [Unit]
   Description=Anchor Open Omniscience blocks
   
   [Service]
   Type=oneshot
   ExecStart=/usr/bin/curl -X POST "http://localhost:8000/api/blockchain/anchor-current-block"
   ```

2. Create timer file `/etc/systemd/system/blockchain-anchor.timer`:
   ```ini
   [Unit]
   Description=Anchor blocks every 24 hours
   
   [Timer]
   OnCalendar=*-*-* 00:00:00
   Persistent=true
   
   [Install]
   WantedBy=timers.target
   ```

3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable blockchain-anchor.timer
   sudo systemctl start blockchain-anchor.timer
   ```

---

## 🛠️ Troubleshooting

### Common Issues

#### Issue: Blockchain module not enabled

**Symptom**: Articles are not being added to blockchain

**Solution**: Check `configs/blockchain.yml`:

```yaml
blockchain:
  enabled: true  # Make sure this is true
```

#### Issue: Database permission errors

**Symptom**: `sqlite3.OperationalError: unable to open database file`

**Solution**: Create the data directory and set permissions:

```bash
mkdir -p data/blockchain
chmod 755 data/blockchain
chown -R $USER:$USER data/
```

#### Issue: Ethereum provider not initialized

**Symptom**: `Ethereum provider not initialized`

**Solution**: 
1. Check that `web3` is installed: `pip show web3`
2. Check that your Ethereum node is running
3. Check the RPC URL in `configs/blockchain.yml`
4. Test the connection:
   ```python
   import web3
   w3 = web3.Web3(web3.HTTPProvider("http://localhost:8545"))
   print(w3.is_connected())  # Should print True
   ```

#### Issue: IPFS provider not initialized

**Symptom**: `IPFS provider not initialized`

**Solution**:
1. Check that `ipfshttpclient` is installed: `pip show ipfshttpclient`
2. Check that IPFS daemon is running: `ipfs id`
3. Check the host and port in `configs/blockchain.yml`

#### Issue: Arweave provider not initialized

**Symptom**: `Arweave provider not initialized`

**Solution**:
1. Check that `arweave-python` is installed: `pip show arweave-python`
2. Check that wallet file exists at the specified path
3. Check that you have AR tokens in your wallet

### Debug Mode

Enable debug logging to see detailed information:

```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Start Open Omniscience
python -m src.api.main
```

### Check Logs

```bash
# View recent logs
tail -f logs/open_omniscience.log

# Filter for blockchain-related logs
grep blockchain logs/open_omniscience.log
```

---

## 📊 Monitoring

### Check Service Health

```bash
curl "http://localhost:8000/api/blockchain/status"
```

### Check Chain Integrity

```bash
curl "http://localhost:8000/api/blockchain/chain-integrity"
```

### List All Blocks

```bash
curl "http://localhost:8000/api/blockchain/blocks"
```

### List All Anchors

```bash
curl "http://localhost:8000/api/blockchain/anchors"
```

### Get Statistics

```bash
# Get service status with statistics
curl "http://localhost:8000/api/blockchain/status" | jq '.statistics'
```

---

## 🔒 Security Best Practices

### Private Keys

**⚠️ IMPORTANT**: Never commit private keys to version control!

**Recommended**: Use environment variables for private keys:

```bash
# .env file (add to .gitignore!)
BLOCKCHAIN_ETHEREUM_PRIVATE_KEY="0xyour_private_key"
BLOCKCHAIN_ARWEAVE_WALLET_KEY='{"kty":"RSA",...}'
```

### Database Backup

Regularly back up your blockchain database:

```bash
# Backup local hash chain
cp data/blockchain/local_hash_chain.db data/blockchain/local_hash_chain.db.backup

# Backup anchors database
cp data/blockchain/anchors.db data/blockchain/anchors.db.backup

# Or use sqlite3 to dump
sqlite3 data/blockchain/local_hash_chain.db ".dump" > blockchain_backup.sql
```

### Network Security

- **Firewall**: Restrict access to your Ethereum/IPFS/Arweave nodes
- **HTTPS**: Use HTTPS for all API endpoints in production
- **Rate Limiting**: Consider adding rate limiting to prevent abuse

---

## 📈 Performance Optimization

### Database Optimization

SQLite is generally fast, but for large datasets:

1. **Vacuum the database** (reclaims space):
   ```bash
   sqlite3 data/blockchain/local_hash_chain.db "VACUUM;"
   ```

2. **Analyze the database** (updates statistics):
   ```bash
   sqlite3 data/blockchain/local_hash_chain.db "ANALYZE;"
   ```

3. **Increase cache size**:
   ```bash
   sqlite3 data/blockchain/local_hash_chain.db "PRAGMA cache_size = -10000;"  # 10MB cache
   ```

### Block Size Optimization

Adjust `articles_per_block` and `time_per_block` based on your use case:

| Use Case | articles_per_block | time_per_block | Notes |
|----------|---------------------|----------------|-------|
| High volume | 1000 | 3600 (1 hour) | More frequent blocks |
| Low volume | 10 | 86400 (24 hours) | Fewer, larger blocks |
| Balanced | 100 | 86400 (24 hours) | Default |

---

## 🆘 Support

### Getting Help

1. **Check the documentation**:
   - [Blockchain Architecture](BLOCKCHAIN_ARCHITECTURE.md)
   - [Blockchain API Reference](BLOCKCHAIN_API.md)

2. **Check the logs**:
   ```bash
   tail -f logs/open_omniscience.log | grep blockchain
   ```

3. **Check the tests**:
   ```bash
   python -m unittest tests.blockchain -v
   ```

4. **Create an issue**:
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues)
   - Include: Error messages, logs, configuration, steps to reproduce

### Community

- **Discussions**: [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions)
- **Email**: open-omniscience@ideotion.com

---

## 📚 Additional Resources

- [Open Omniscience Documentation](DOCUMENTATION.md)
- [Main README](../README.md)
- [API Documentation](API_DOCUMENTATION.md)
- [Ethereum Documentation](https://ethereum.org/en/developers/docs/)
- [IPFS Documentation](https://docs.ipfs.tech/)
- [Arweave Documentation](https://docs.arweave.org/)

---

## 📜 License

This setup guide and the blockchain verification system are licensed under **GNU GPLv3**. See [LICENSE](../../LICENSE) for details.
