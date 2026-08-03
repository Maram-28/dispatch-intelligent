FROM quay.io/keycloak/keycloak:26.0
COPY import/lvmh-tickets-realm.json /opt/keycloak/data/import/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start", "--optimized", "--import-realm"]
