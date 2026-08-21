from abc import ABC,abstractmethod
from datetime import datetime,timezone
import httpx
from .models import ChainName,ERC20Transfer,NormalizedTransaction
TRANSFER_TOPIC="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
class BlockchainProvider(ABC):
    @abstractmethod
    async def get_normalized_transaction(self,chain:ChainName,tx_hash:str)->NormalizedTransaction:raise NotImplementedError
    @abstractmethod
    async def get_address_movements(self,chain:ChainName,address:str,after_block:int,max_blocks:int=20)->tuple[int,list[dict]]:raise NotImplementedError
def _hex_int(value:str|None)->int:return int(value or "0x0",16)
def _topic_address(topic:str)->str:
    if not isinstance(topic,str) or len(topic)!=66:raise ValueError("invalid indexed address topic")
    return "0x"+topic[-40:].lower()
def decode_erc20_transfer_logs(logs:list[dict])->list[ERC20Transfer]:
    transfers=[]
    for log in logs:
        topics=log.get("topics") or []
        if len(topics)!=3 or str(topics[0]).lower()!=TRANSFER_TOPIC:continue
        address=log.get("address")
        data=log.get("data")
        if not isinstance(address,str) or len(address)!=42 or not isinstance(data,str):
            continue
        transfers.append(ERC20Transfer(log_index=_hex_int(log.get("logIndex")),token_contract=address.lower(),from_address=_topic_address(topics[1]),to_address=_topic_address(topics[2]),raw_amount=str(_hex_int(data))))
    return transfers
class RpcProviderError(RuntimeError):pass
class JsonRpcProvider(BlockchainProvider):
    def __init__(self,rpc_urls:dict[ChainName,str],timeout_seconds:float=20):self.rpc_urls,self.timeout_seconds=rpc_urls,timeout_seconds
    async def _call(self,chain:ChainName,method:str,params:list)->dict|None:
        url=self.rpc_urls.get(chain)
        if not url:raise RpcProviderError(f"RPC URL is not configured for {chain}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response=await client.post(url,json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
                payload=response.json()
        except (httpx.HTTPError,ValueError) as exc:
            raise RpcProviderError(f"RPC {method} request failed") from exc
        if payload.get("jsonrpc")!="2.0" or payload.get("id")!=1:raise RpcProviderError(f"RPC {method} returned an invalid response")
        if payload.get("error"):raise RpcProviderError(f"RPC {method} failed: {payload['error'].get('message','provider error')}")
        return payload.get("result")
    async def get_normalized_transaction(self,chain:ChainName,tx_hash:str)->NormalizedTransaction:
        transaction=await self._call(chain,"eth_getTransactionByHash",[tx_hash])
        if not transaction:raise LookupError("transaction not found")
        receipt=await self._call(chain,"eth_getTransactionReceipt",[tx_hash])
        if not receipt:raise LookupError("transaction receipt not found")
        block_hex=transaction.get("blockNumber") or receipt.get("blockNumber")
        if not block_hex:raise LookupError("transaction is pending and has no confirmed block")
        block=await self._call(chain,"eth_getBlockByNumber",[block_hex,False])
        if not block:raise LookupError("transaction block not found")
        if str(receipt.get("transactionHash",transaction["hash"])).lower()!=str(transaction["hash"]).lower():raise RpcProviderError("transaction and receipt hashes do not match")
        if receipt.get("blockNumber") and receipt["blockNumber"]!=block_hex:raise RpcProviderError("transaction and receipt block numbers do not match")
        return NormalizedTransaction(hash=str(transaction["hash"]).lower(),chain=chain,block_number=_hex_int(block_hex),timestamp=datetime.fromtimestamp(_hex_int(block.get("timestamp")),tz=timezone.utc),status="success" if _hex_int(receipt.get("status"))==1 else "failed",from_address=str(transaction["from"]).lower(),to_address=str(transaction["to"]).lower() if transaction.get("to") else None,native_value_wei=str(_hex_int(transaction.get("value"))),input=transaction.get("input") or "0x",erc20_transfers=decode_erc20_transfer_logs(receipt.get("logs") or []))

    async def get_address_movements(self,chain:ChainName,address:str,after_block:int,max_blocks:int=20)->tuple[int,list[dict]]:
        latest=_hex_int(await self._call(chain,"eth_blockNumber",[]))
        end=min(latest,after_block+max_blocks)
        if end<=after_block:return latest,[]
        target=address.lower();found={}
        for number in range(after_block+1,end+1):
            block=await self._call(chain,"eth_getBlockByNumber",[hex(number),True]) or {}
            for tx in block.get("transactions") or []:
                if str(tx.get("from","")).lower()==target or str(tx.get("to","")).lower()==target:
                    h=str(tx["hash"]).lower();found[h]={"transaction_hash":h,"block_number":number,"kind":"native_or_contract","direction":"out" if str(tx.get("from","")).lower()==target else "in"}
        padded="0x"+"0"*24+target[2:]
        for direction,topics in (("out",[TRANSFER_TOPIC,padded]),("in",[TRANSFER_TOPIC,None,padded])):
            for start in range(after_block+1,end+1,10):
                logs=await self._call(chain,"eth_getLogs",[{"fromBlock":hex(start),"toBlock":hex(min(end,start+9)),"topics":topics}]) or []
                for log in logs:
                    h=str(log["transactionHash"]).lower();found.setdefault(h,{"transaction_hash":h,"block_number":_hex_int(log.get("blockNumber")),"kind":"erc20","direction":direction})
        return end,sorted(found.values(),key=lambda x:(x["block_number"],x["transaction_hash"]))
