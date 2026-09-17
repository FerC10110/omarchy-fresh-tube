-- Fresh Tube's mpv companion. Loaded by `fresh-tube play` with
--   --script-opt=fresh_tube-id=<videoId> --script-opt=fresh_tube-bin=<path to bin/fresh-tube>
-- It tells the plugin when the video reaches its end (so the video leaves the
-- Watch later list) and remembers the window size when mpv closes.
local mp = require("mp")

local video_id = mp.get_opt("fresh_tube-id")
local bin = mp.get_opt("fresh_tube-bin")
if not video_id or video_id == "" or not bin or bin == "" then
  return
end

local done_sent = false
local last_w, last_h = 0, 0

-- Fire and forget: detached, and never tied to the playback lifetime, so a
-- call made while mpv is shutting down still runs.
local function run(args)
  mp.command_native({
    name = "subprocess",
    args = args,
    detach = true,
    playback_only = false,
  })
end

local function mark_done()
  if done_sent then
    return
  end
  done_sent = true
  run({ bin, "done", "--", video_id })
end

-- Normal end of the file.
mp.register_event("end-file", function(event)
  if event.reason == "eof" then
    mark_done()
  end
end)

-- With keep-open=yes in the user's mpv.conf, mpv pauses at the end instead of
-- unloading the file; eof-reached covers that.
mp.observe_property("eof-reached", "bool", function(_, reached)
  if reached then
    mark_done()
  end
end)

mp.observe_property("osd-dimensions", "native", function(_, dims)
  if dims and dims.w and dims.h and dims.w > 0 and dims.h > 0 then
    last_w, last_h = math.floor(dims.w), math.floor(dims.h)
  end
end)

mp.register_event("shutdown", function()
  if last_w > 0 and last_h > 0 then
    run({ bin, "prefs", "set", "playerWidth", tostring(last_w), "playerHeight", tostring(last_h) })
  end
end)
