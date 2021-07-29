import math, random, argparse, time, uuid

parser = argparse.ArgumentParser(description='Neural Network Trainer Template')
parser.add_argument('-restore_true', dest='restore_true', action='store_true', help='Model restoring')
parser.add_argument('-restore_false', dest='restore_false', action='store_false', help='Model restoring')
parser.add_argument('-name', dest='name', default='test_' + str(uuid.uuid4())[:8], help='Name of the run')
args = parser.parse_args()

print(f"args.name {args.name}")
print("Done")
print(f"args.restore_true {args.restore_true}")
print(f"args.restore_false {args.restore_false}")