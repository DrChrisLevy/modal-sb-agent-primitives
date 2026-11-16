"""Keep the loop outside; allow Sandbox egress only to one IP address."""

import modal

from s1_minimal import main


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s2-allowlist", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.13").apt_install("git")
    return modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600,
        outbound_cidr_allowlist=["1.1.1.1/32"],
    )
# endregion


if __name__ == "__main__":
    main(create_sandbox=create_sandbox)
