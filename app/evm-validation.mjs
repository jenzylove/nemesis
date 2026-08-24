const EVM_ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;
const TRANSACTION_HASH_PATTERN = /^0x[0-9a-fA-F]{64}$/;

export function validateEvmAddress(input) {
  const value = input.trim();
  if (!value) return "Enter the affected wallet address.";
  if (!value.startsWith("0x")) return "Wallet address must start with 0x.";
  if (value.length !== 42) return "Wallet address must contain exactly 40 hexadecimal characters after 0x.";
  if (!EVM_ADDRESS_PATTERN.test(value)) return "Wallet address may contain only hexadecimal characters (0-9 and A-F).";
  return "";
}

export function validateTransactionHash(input) {
  const value = input.trim();
  if (!value) return "";
  if (!value.startsWith("0x")) return "Transaction hash must start with 0x.";
  if (value.length !== 66) return "Transaction hash must contain exactly 64 hexadecimal characters after 0x.";
  if (!TRANSACTION_HASH_PATTERN.test(value)) return "Transaction hash may contain only hexadecimal characters (0-9 and A-F).";
  return "";
}
