#!/usr/bin/env python3
"""Publish, or unpublish, a single investigation.

Publishing is deliberate curation, so it is an operator action against
Firestore rather than an API route. There is no endpoint that can flip this
flag, which means no request can ever make a private case public.

    python scripts/publish-case.py NMS-260826-915B337C
    python scripts/publish-case.py NMS-260826-915B337C --unpublish

Requires application default credentials with access to the project.
"""
import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("--unpublish", action="store_true",
                        help="return the case to owner-only access")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "nemesis-506114"))
    parser.add_argument("--collection", default=os.getenv("FIRESTORE_CASES_COLLECTION", "cases"))
    args = parser.parse_args()

    from google.cloud import firestore

    client = firestore.Client(project=args.project)
    ref = client.collection(args.collection).document(args.case_id)
    snapshot = ref.get()
    if not snapshot.exists:
        print(f"case {args.case_id} not found in {args.project}/{args.collection}")
        return 1

    record = snapshot.to_dict() or {}
    publish = not args.unpublish
    ref.update({"is_public_case": publish})

    state = "published" if publish else "unpublished"
    print(f"{args.case_id} {state}")
    print(f"  wallet {record.get('wallet_address')}")
    print(f"  state  {record.get('state')}")
    if publish:
        print("  A published case is served read-only and without the owner account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
