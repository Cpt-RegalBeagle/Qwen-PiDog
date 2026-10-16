def _rgb_strip_set_mode(mode: str, color: str = 'green'):
    """Set RGB strip mode via RPC call - SDK only accepts 2 args (mode, color)"""
    if rpc_client is not None:
        try:
            # Normalize invalid modes to valid ones BEFORE calling RPC - OFFICIAL SUNFOUNDER MODES
            valid_modes = ['breath', 'boom', 'bark']
            
            if mode == 'listen':
                mode = 'breath'
            elif mode == 'close':
                mode = 'breath'
                color = 'black'  # Use black to turn off
            
            _rpc_call('rgb_strip_set_mode', mode, color)
        except Exception as e:
            print(f"  [RPC] Failed to set RGB mode: {e}", file=sys.stderr)


def _is_speaking() -> bool:
    """Queries our background RPC server appliance directly to verify if the 

    robot's physical speaker is currently playing back audio waves."""
    global is_speaking
    
    # 1. Check our internal client-side software flag first
    if is_speaking:
        return True
        
    # 2. Execute a live network query straight to our RPC hardware server
    try:
        # Use our active rpc_client proxy connection handle
        # If the server's music module is active, it returns True natively
        if 'rpc_client' in globals() or 'rpc_client' in locals():
            server_status = rpc_client.is_speaking()
            return bool(server_status)
    except Exception as e:
        # If the network link glitches or isn't ready, fail safe to False so we don't lock the thread
        pass
        
    return False
