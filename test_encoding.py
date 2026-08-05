# Testing the double-encoding hypothesis
# Sequence: c3 97 c2 93
corrupted_hex = "c3 97 c2 93"
corrupted_bytes = bytes.fromhex(corrupted_hex.replace(" ", ""))

# 1. Decode as UTF-8 to get the "wrong" characters
wrong_str = corrupted_bytes.decode('utf-8')
print(f"Wrong string: {repr(wrong_str)}")

# 2. Encode back to latin-1 (which preserves byte values for 00-FF)
try:
    original_bytes = wrong_str.encode('latin-1')
    print(f"Original bytes: {original_bytes.hex(' ')}")
    
    # 3. Decode as UTF-8 (interpreting as Hebrew)
    correct_str = original_bytes.decode('utf-8')
    print(f"Corrected string: {correct_str}")
except Exception as e:
    print(f"Error during correction: {e}")

# Let's try another one: c3 97 c2 9c
# D7 9C is Lamed (ל)
corrupted_lamed = bytes.fromhex("c3 97 c2 9c")
print(f"Corrected Lamed: {corrupted_lamed.decode('utf-8').encode('latin-1').decode('utf-8')}")
