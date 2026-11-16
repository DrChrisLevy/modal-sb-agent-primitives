"""Expose a dummy credential as a Sandbox environment variable."""

import modal

from s1_minimal import main


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s2-secret", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.13").apt_install("git")
    secret = modal.Secret.from_name("blog-demo-key")
    return modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600,
        secrets=[secret],
    )
# endregion


if __name__ == "__main__":
    main(create_sandbox=create_sandbox)
