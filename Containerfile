# Dev/test environment for premortem.
# Textual (elicit/) and everything else runs entirely inside this container -
# no host GUI split needed. This stays fully offline at runtime (see run-dev.sh);
# only `podman build` needs network, to fetch packages via dnf/pip.

FROM registry.fedoraproject.org/fedora:44

# Install Python the same way your host does: via dnf, from Fedora's own
# signed repos. No extra registries, no separate trust chain to reason about.
#
# pango + gdk-pixbuf2 are WeasyPrint's runtime dependencies (text shaping/
# layout and image decoding respectively) - WeasyPrint 53+ dropped the older
# cairo/pycairo dependency chain in favor of its own PDF backend, so this is
# the whole native dependency list.
RUN dnf install -y python3 python3-pip pango gdk-pixbuf2 && dnf clean all

# Defense in depth: rootless Podman already maps this container's "root" to
# your unprivileged host user, but we also drop to a dedicated non-root user
# *inside* the container — so nothing here runs as root at any layer, ever.
RUN useradd --create-home appuser
USER appuser
WORKDIR /home/appuser/app

# Only the dependency list is baked into the image — not your code. Code
# arrives later as a live mount, so edits on the host appear instantly with
# no rebuild required.
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
