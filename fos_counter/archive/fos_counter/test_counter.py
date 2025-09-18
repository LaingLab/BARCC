from fos_counter import count_fos_positive
import os

# Use placeholder paths (replace with real ones, but this won't save files—it just checks the return)
try:
    result = count_fos_positive('dummy_input.tif', 'dummy_output.tif')
    print(f"Result type: {type(result)}")  # Should be <class 'tuple'>
    print(f"Length: {len(result)}")  # Should be 2
    print(f"First item type: {type(result[0])}")  # <class 'int'>
    print(f"Second item type: {type(result[1])}")  # <class 'list'>
except Exception as e:
    print(f"Error: {e}")