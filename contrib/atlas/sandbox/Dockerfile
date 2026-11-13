FROM sha256:78976a69c067520ef8be34cde307ef9f6fea6dcefa50edb57039773d241ca0db AS build
COPY . /build/
RUN /usr/local/bin/python3 -I -m pip --isolated install --disable-pip-version-check --no-cache-dir --only-binary=:all: --require-hashes --no-deps --no-index --find-links=/build/wheels --target=/opt/atlas/python -r /build/requirements.lock && /usr/local/bin/python3 -I /build/install_assets.py
FROM scratch
COPY --from=build / /
COPY --chmod=0555 skills /opt/atlas/skills
COPY --chmod=0555 podman_supervisor.py /opt/atlas/podman_supervisor.py
ENV PATH=/opt/atlas/bin:/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent TMPDIR=/tmp
LABEL org.opencontainers.image.title="Atlas document sandbox" org.opencontainers.image.description="Offline document-only auxiliary Python and Node runtime; no agent, browser, desktop, Telegram or control helpers" qyp.task="atlas-document"
USER 65532:65532
WORKDIR /work
ENTRYPOINT ["/opt/atlas/bin/python3"]
CMD ["--version"]
