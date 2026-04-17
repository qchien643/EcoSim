"""Write test output to file for full reading."""
import sys
import io

# Redirect stdout to file
output_file = r"e:\code\project\DUT_STARTUP\EcoSim\oasis\test_output.txt"
original_stdout = sys.stdout
sys.stdout = io.open(output_file, "w", encoding="utf-8")

sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")
exec(open(r"e:\code\project\DUT_STARTUP\EcoSim\oasis\test_full_integration.py", encoding="utf-8").read())

sys.stdout.close()
sys.stdout = original_stdout
print(f"Output written to {output_file}")
