TransportPacket
Rename targets
PacketEnvelope       -> TransportPacket
create_packet        -> create_transport_packet
validate_packet      -> validate_transport_packet
sign_packet          -> sign_transport_packet
deflate_egress       -> encode_transport_packet
inflate_ingress      -> decode_transport_packet
Type components
These should keep the same underlying concepts but align naming around transport:

PacketHeader         -> TransportHeader
PacketAddress        -> TransportAddress
PacketSecurity       -> TransportSecurity
PacketGovernance     -> TransportGovernance
PacketLineage        -> TransportLineage
PacketAttachment     -> TransportAttachment
HopEntry             -> TransportHop
DelegationLink       -> DelegationLink   # can stay
TenantContext        -> TenantContext    # keep