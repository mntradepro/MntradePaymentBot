"""BSC USDT Payment Checker — 3 metodes ar fallback
FIX: Stingra tolerance ±0.005 USDT + atomāra TX rezervācija
"""
import aiohttp
import logging
import asyncio
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from config import config
from database import db

logger = logging.getLogger(__name__)
CHECK_WINDOW_MINUTES = 60
BSC_RPC_URLS = [
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.defibit.io/",
    "https://bsc-dataseed1.ninicoin.io/",
]
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
RPC_BLOCK_CHUNK = 128

# Absolūtā tolerance — ±0.005 USDT (nevis %)
# 10.00 matčo tikai 9.995–10.005, bet NE 10.01
TOLERANCE_USDT = Decimal("0.005")

# Lock lai nevar divi procesi vienlaicīgi piešķirt vienu TX
_tx_lock = asyncio.Lock()


async def _rpc_post(session, url, payload, timeout=10):
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        return await resp.json()


async def _check_via_rpc(wallet, min_amount, max_amount) -> List[Tuple[str, int]]:
    wallet_topic = "0x" + wallet.lower().replace("0x", "").zfill(64)
    for rpc_url in BSC_RPC_URLS:
        try:
            async with aiohttp.ClientSession() as session:
                data = await _rpc_post(session, rpc_url, {"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]})
                current_block = int(data["result"], 16)
                logger.info(f"[RPC] {rpc_url[:35]} block={current_block}")
                total_blocks = (CHECK_WINDOW_MINUTES * 60) // 3
                start_block = current_block - total_blocks
                all_logs = []
                block = start_block
                while block < current_block:
                    chunk_end = min(block + RPC_BLOCK_CHUNK - 1, current_block)
                    resp = await _rpc_post(session, rpc_url, {
                        "jsonrpc":"2.0","id":2,"method":"eth_getLogs",
                        "params":[{"fromBlock":hex(block),"toBlock":hex(chunk_end),
                                   "address":config.USDT_CONTRACT,
                                   "topics":[TRANSFER_TOPIC, None, wallet_topic]}]
                    }, timeout=12)
                    if "error" in resp:
                        err = resp["error"]
                        if err.get("code") == -32005 or "limit" in str(err.get("message","")).lower():
                            half = max((chunk_end - block) // 2, 10)
                            chunk_end = block + half
                            resp = await _rpc_post(session, rpc_url, {
                                "jsonrpc":"2.0","id":2,"method":"eth_getLogs",
                                "params":[{"fromBlock":hex(block),"toBlock":hex(chunk_end),
                                           "address":config.USDT_CONTRACT,
                                           "topics":[TRANSFER_TOPIC, None, wallet_topic]}]
                            }, timeout=12)
                            if "error" in resp:
                                block = chunk_end + 1; continue
                    logs = resp.get("result", [])
                    if logs: all_logs.extend(logs)
                    block = chunk_end + 1
                logger.info(f"[RPC] Atrasti {len(all_logs)} USDT transferi")
                results = []
                for log_entry in reversed(all_logs):
                    tx_hash = log_entry.get("transactionHash", "")
                    try: value = int(log_entry.get("data", "0x0"), 16)
                    except ValueError: continue
                    if min_amount <= value <= max_amount:
                        results.append((tx_hash, value))
                return results
        except Exception as e:
            logger.warning(f"[RPC] {rpc_url[:30]}: {e}"); continue
    return []


async def _check_via_meganode(wallet, min_amount, max_amount) -> List[Tuple[str, int]]:
    api_key = getattr(config, 'MEGANODE_API_KEY', '')
    if not api_key: return []
    wallet_topic = "0x" + wallet.lower().replace("0x", "").zfill(64)
    url = f"https://bsc-mainnet.nodereal.io/v1/{api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            data = await _rpc_post(session, url, {"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]})
            if "error" in data: logger.error(f"[MegaNode] {data['error']}"); return []
            current_block = int(data["result"], 16)
            from_block = current_block - (CHECK_WINDOW_MINUTES * 60) // 3
            resp = await _rpc_post(session, url, {
                "jsonrpc":"2.0","id":2,"method":"eth_getLogs",
                "params":[{"fromBlock":hex(from_block),"toBlock":"latest",
                           "address":config.USDT_CONTRACT,
                           "topics":[TRANSFER_TOPIC, None, wallet_topic]}]
            }, timeout=15)
            if "error" in resp: logger.error(f"[MegaNode] {resp['error']}"); return []
            logs = resp.get("result", [])
            logger.info(f"[MegaNode] {len(logs)} USDT transferi")
            results = []
            for log_entry in reversed(logs):
                tx_hash = log_entry.get("transactionHash", "")
                try: value = int(log_entry.get("data", "0x0"), 16)
                except ValueError: continue
                if min_amount <= value <= max_amount:
                    results.append((tx_hash, value))
            return results
    except Exception as e:
        logger.error(f"[MegaNode] {e}"); return []


async def _check_via_etherscan(wallet, min_amount, max_amount, min_timestamp) -> List[Tuple[str, int]]:
    if not config.BSCSCAN_API_KEY: return []
    try:
        params = {"chainid":56,"module":"account","action":"tokentx",
                  "contractaddress":config.USDT_CONTRACT,"address":wallet,
                  "startblock":0,"endblock":99999999,"sort":"desc","offset":50,"page":1,
                  "apikey":config.BSCSCAN_API_KEY}
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.etherscan.io/v2/api", params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200: return []
                data = await resp.json()
        if data.get("status") != "1": return []
        results = []
        for tx in data.get("result", []):
            if tx.get("to","").lower() != wallet.lower(): continue
            value = int(tx.get("value","0"))
            if int(tx.get("timeStamp",0)) < min_timestamp: continue
            if min_amount <= value <= max_amount:
                results.append((tx.get("hash",""), value))
        return results
    except Exception as e:
        logger.error(f"[Etherscan] {e}"); return []


async def check_payment(wallet, expected_amount, user_id):
    """Pārbauda vai ir USDT maksājums ar STINGRU toleranci un atomāru TX lock.

    Tolerance: ±0.005 USDT (absolūta, nevis %).
    Piemērs: expected=10.01 → meklē 10.005–10.015
             expected=10.00 → meklē 9.995–10.005
    Tādējādi 10.00 TX NEVAR matčoties ar 10.01 expected.
    """
    try:
        exp_decimal = Decimal(str(expected_amount))
        min_usdt = exp_decimal - TOLERANCE_USDT
        max_usdt = exp_decimal + TOLERANCE_USDT
        min_a = int(min_usdt * Decimal("1e18"))
        max_a = int(max_usdt * Decimal("1e18"))
        min_ts = int((datetime.utcnow() - timedelta(minutes=CHECK_WINDOW_MINUTES)).timestamp())

        logger.info(f"[check_payment] user={user_id} expected={expected_amount} USDT range=[{min_usdt},{max_usdt}]")

        if wallet.startswith("0xYour") or len(wallet) < 10:
            return None

        # Savācam kandidātus no visiem avotiem
        candidates = []

        rpc_results = await _check_via_rpc(wallet, min_a, max_a)
        if rpc_results:
            candidates.extend(rpc_results)
            logger.info(f"[RPC] {len(rpc_results)} kandidāti")

        if not candidates:
            mega_results = await _check_via_meganode(wallet, min_a, max_a)
            if mega_results:
                candidates.extend(mega_results)
                logger.info(f"[MegaNode] {len(mega_results)} kandidāti")

        if not candidates:
            ether_results = await _check_via_etherscan(wallet, min_a, max_a, min_ts)
            if ether_results:
                candidates.extend(ether_results)
                logger.info(f"[Etherscan] {len(ether_results)} kandidāti")

        if not candidates:
            return None

        # ATOMĀRA TX REZERVĀCIJA — tikai viens process var piešķirt TX
        async with _tx_lock:
            # Atrast labāko kandidātu — tuvāko expected summai
            exp_wei = int(exp_decimal * Decimal("1e18"))
            candidates.sort(key=lambda c: abs(c[1] - exp_wei))

            for tx_hash, tx_value in candidates:
                if not await db.is_tx_used(tx_hash):
                    # Uzreiz atzīmē kā used PIRMS atgriež — lai cits process to nevar paņemt
                    await db.mark_tx_used(tx_hash, user_id)
                    actual_usdt = Decimal(tx_value) / Decimal("1e18")
                    logger.info(f"✅ TX={tx_hash[:20]} amount={actual_usdt} USDT (expected={expected_amount}) user={user_id}")
                    return tx_hash

            logger.warning(f"[check_payment] Visi {len(candidates)} TX jau izmantoti, user={user_id}")
            return None

    except Exception as e:
        logger.error(f"check_payment: {e}", exc_info=True)
        return None
