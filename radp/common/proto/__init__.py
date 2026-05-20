"""Auto-generated gRPC stubs live here. Regenerate via `bash scripts/gen_proto.sh`.

We re-export the generated modules as ``Any`` so the rest of the codebase
doesn't drown in `attr-defined` errors from protobuf's dynamic class creation.
Real type safety for these would require ``mypy-protobuf`` + .pyi generation.
"""

from typing import Any

from radp.common.proto import radp_pb2 as _radp_pb2
from radp.common.proto import radp_pb2_grpc as _radp_pb2_grpc

radp_pb2: Any = _radp_pb2
radp_pb2_grpc: Any = _radp_pb2_grpc

__all__ = ["radp_pb2", "radp_pb2_grpc"]
