import os

import uvicorn

from .app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("SNIP_HOST", "127.0.0.1"),
        port=int(os.environ.get("SNIP_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
