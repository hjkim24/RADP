#!/usr/bin/env bash
# Regenerate gRPC Python stubs from radp/common/proto/radp.proto.
# Output is gitignored; commit only the .proto source.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="${ROOT}/radp/common/proto"

python -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${PROTO_DIR}" \
  --grpc_python_out="${PROTO_DIR}" \
  "${PROTO_DIR}/radp.proto"

# protoc emits absolute imports ("import radp_pb2"); rewrite to package-relative
# so `from radp.common.proto import radp_pb2_grpc` works.
sed -i.bak 's/^import radp_pb2 as radp__pb2$/from . import radp_pb2 as radp__pb2/' \
  "${PROTO_DIR}/radp_pb2_grpc.py"
rm -f "${PROTO_DIR}/radp_pb2_grpc.py.bak"

echo "Generated: ${PROTO_DIR}/radp_pb2.py, ${PROTO_DIR}/radp_pb2_grpc.py"
