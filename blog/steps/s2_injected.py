"""Inject a dummy HTTPS header outside the Sandbox, not into its environment."""

import modal
import modal.experimental

from s1_minimal import main


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s2-injected", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.13").apt_install("git")
    policy = modal.experimental.OutboundPolicy().with_header_replacement(
        domain="httpbin.org",
        secret=modal.Secret.from_name("blog-demo-key"),
        headers={"Authorization": "Bearer $BLOG_DEMO_KEY"},
    )
    return modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600,
        _experimental_outbound_policy=policy,
    )
# endregion


if __name__ == "__main__":
    main(create_sandbox=create_sandbox)
