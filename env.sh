# Usage: source env.sh
# Modal auth comes from your active profile in ~/.modal.toml (see `modal setup`).
# ENDPOINT_URL and MODAL_PROXY_TOKEN live outside this folder in ~/.config/modal-learn/secrets.env.
[ -f ~/.config/modal-learn/secrets.env ] && source ~/.config/modal-learn/secrets.env
unset RUST_LOG MODAL_SERVER_URL MODAL_ENVIRONMENT
