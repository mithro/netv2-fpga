void compute_keys( unsigned long Ksv_hi, unsigned long Ksv_lo, unsigned int source, unsigned long long *key );
int derive_km(void);
void hdcp_isr(void);
void hdcp_init(void);
void init_rect(int mode, int hack);

int link_redo;
