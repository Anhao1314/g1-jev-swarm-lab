"""Offline geometric selection. Not a simulator, controller, or safety gate."""
import math

ALPHAS = (0.0, 0.25, 0.5)
LENGTH_M = 8.0
STRICT_LATERAL_M = 0.28
STRICT_HEADING_DEG = 8.0

def select(position_xy, actual_yaw_rad, mission_yaw_rad, waypoint_xy):
    values = (*position_xy, actual_yaw_rad, mission_yaw_rad, *waypoint_xy)
    if len(position_xy) != 2 or len(waypoint_xy) != 2 or not all(math.isfinite(x) for x in values):
        raise ValueError('invalid_geometric_state')
    yaw_delta = math.atan2(math.sin(mission_yaw_rad-actual_yaw_rad),
                          math.cos(mission_yaw_rad-actual_yaw_rad))
    candidates = []
    for alpha in ALPHAS:
        delta = alpha * yaw_delta
        # Exact-line proxy at the ORIGINAL actual-start forward completion L.
        # Real tracking may deviate: neither necessary nor sufficient for real success.
        forward = math.cos(delta) > 0
        lateral = LENGTH_M * math.tan(delta) if forward else None
        compatible = forward and abs(lateral) <= STRICT_LATERAL_M and abs(math.degrees(delta)) <= STRICT_HEADING_DEG
        predicted = None
        error = None
        if forward:
            c,s = math.cos(actual_yaw_rad),math.sin(actual_yaw_rad)
            predicted = [position_xy[0]+c*LENGTH_M-s*lateral,
                         position_xy[1]+s*LENGTH_M+c*lateral]
            error = math.hypot(predicted[0]-waypoint_xy[0],predicted[1]-waypoint_xy[1])
        candidates.append({'alpha':alpha,'nominal_line_compatible':compatible,
                           'predicted_local_lateral_m':lateral,'predicted_local_heading_deg':math.degrees(delta),
                           'predicted_world_endpoint':predicted,'predicted_waypoint_error_m':error})
    eligible = [r for r in candidates if r['nominal_line_compatible']]
    if not eligible:
        return {'decision':'UNRESOLVED','alpha':None,'candidates':candidates}
    chosen = min(eligible,key=lambda r:(r['predicted_waypoint_error_m'],r['alpha']))
    return {'decision':'NOMINAL_GEOMETRY_PROPOSAL','alpha':chosen['alpha'],'candidates':candidates,
            'scope':'Choose once at first Walk entry; same alpha for all Walk references. No dynamic guarantee.'}
