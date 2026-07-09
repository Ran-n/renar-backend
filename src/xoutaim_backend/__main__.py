#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:13.871671
Revised: 2026/07/07 13:25:13.871671
"""

import uvicorn


def run():
    uvicorn.run(
        "xoutaim_backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["src"],
        server_header=False,  # don't advertise "uvicorn" + version to scanners
    )


if __name__ == "__main__":
    run()
