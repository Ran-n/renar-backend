import uvicorn


def run():
    uvicorn.run(
        "xoutaim_backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["src"],
    )


if __name__ == "__main__":
    run()
