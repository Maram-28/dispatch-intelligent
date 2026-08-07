FROM quay.io/keycloak/keycloak:26.0
COPY import/lvmh-tickets-realm.json /opt/keycloak/data/import/
COPY themes/lvmh-dispatch /opt/keycloak/themes/lvmh-dispatch
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start", "--optimized", "--import-realm"]