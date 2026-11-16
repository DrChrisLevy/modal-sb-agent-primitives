"""Keep the loop outside; allow Sandbox HTTPS egress only to PyPI."""

import modal

from s1_minimal import main


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s2-domain", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.13").apt_install("git")
    return modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600,
        outbound_domain_allowlist=["pypi.org"],
    )
# endregion


if __name__ == "__main__":
    main(create_sandbox=create_sandbox)
