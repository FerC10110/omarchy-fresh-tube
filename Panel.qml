import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "FreshTubeModel.js" as Model

// The panel is a thin face over bin/fresh-tube: every fetch and every write
// happens in that script, and the panel only shows the JSON it prints.
Panel {
  id: root
  moduleName: "io.github.ferc10110.fresh-tube"
  ipcTarget: "io.github.ferc10110.fresh-tube"
  // Its own IpcHandler below adds refresh and togglePin to open/close/toggle.
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null

  property string view: "videos"
  property var videos: []
  property var errors: []
  property string fetchedAt: ""
  property bool offline: false
  property int channelCount: 0
  property string notice: ""
  property bool noticeIsError: false
  property bool pinned: false
  property int popupWidth: 420
  property int popupHeight: 520
  property bool playerFound: true
  property var pendingPlay: null
  property var prefsQueue: []

  readonly property bool refreshing: refreshCmd.running
  readonly property string program: pluginPath("bin/fresh-tube")
  readonly property string playerCommand: String(setting("playerCommand", "mpv") || "mpv")
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property Item currentFocus: videosView.focusItem

  // Absolute path of a file shipped inside this plugin, wherever it is installed.
  function pluginPath(relative) {
    var url = String(Qt.resolvedUrl(relative))
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  function parseJson(out) {
    try {
      var data = JSON.parse(String(out || ""))
      return data && typeof data === "object" ? data : null
    } catch (e) {
      return null
    }
  }

  function lastLine(err) {
    var lines = String(err || "").trim().split("\n")
    return lines[lines.length - 1].replace(/^fresh-tube: /, "")
  }

  function setNotice(message, isError) {
    notice = message || ""
    noticeIsError = isError === true
  }

  function focusCurrent() {
    Qt.callLater(function() {
      if (root.opened && root.currentFocus) root.currentFocus.forceActiveFocus()
    })
  }

  function applyPayload(data) {
    videos = Array.isArray(data.videos) ? data.videos : []
    errors = Array.isArray(data.errors) ? data.errors : []
    fetchedAt = String(data.fetchedAt || "")
    offline = data.offline === true
    channelCount = Number(data.channelCount) || 0
  }

  function loadCached() {
    cachedCmd.start(["refresh", "--json", "--cached"])
  }

  function reloadCached() { loadCached() }

  function refresh() {
    refreshCmd.start(["refresh", "--json"])
  }

  function checkPlayer() {
    playerCheckCmd.start(["-c", "command -v -- \"$0\"", Model.playerName(root.playerCommand)])
  }

  function removeVideo(videoId) {
    videos = videos.filter(function(v) { return v.videoId !== videoId })
  }

  function play(video) {
    if (!video || seenCmd.running) return
    if (!playerFound) {
      setNotice(Model.playerName(playerCommand) + " not found. Set playerCommand in shell.json.", true)
      return
    }
    try {
      Quickshell.execDetached(Model.playerArgs(playerCommand).concat([video.url]))
    } catch (e) {
      setNotice("Could not start " + Model.playerName(playerCommand) + ": " + e, true)
      return
    }
    pendingPlay = video
    seenCmd.start(["seen", "--", video.videoId])
  }

  function dismiss(video) {
    if (!video || seenCmd.running) return
    pendingPlay = null
    seenCmd.start(["seen", "--", video.videoId])
  }

  // Every `prefs set` rewrites the whole state file, so writes go one at a
  // time through a queue; two in parallel would drop one of the values.
  function queuePref(key, value) {
    prefsQueue = prefsQueue.concat([[key, String(value)]])
    pumpPrefs()
  }

  function pumpPrefs() {
    if (prefsCmd.running || prefsQueue.length === 0) return
    var next = prefsQueue[0]
    prefsQueue = prefsQueue.slice(1)
    prefsCmd.start(["prefs", "set", next[0], next[1]])
  }

  function setPinned(value) {
    var next = value === true
    if (pinned === next) return
    pinned = next
    queuePref("pinned", next ? "true" : "false")
  }

  function togglePin() { setPinned(!pinned) }

  function saveSize(w, h) {
    popupWidth = w
    popupHeight = h
    queuePref("width", w)
    queuePref("height", h)
  }

  onOpenedChanged: {
    if (opened) {
      setNotice("", false)
      view = "videos"
      loadCached()
      refresh()
      focusCurrent()
    }
  }

  onViewChanged: focusCurrent()

  onPlayerCommandChanged: checkPlayer()

  Component.onCompleted: {
    prefsGetCmd.start(["prefs", "get"])
    checkPlayer()
    loadCached()
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh() }
    function togglePin(): void { root.togglePin() }
  }

  FreshTubeCommand {
    id: prefsGetCmd
    program: root.program
    onFinished: function(code, out, err) {
      var data = root.parseJson(out)
      if (!data) return
      root.popupWidth = Number(data.width) || 420
      root.popupHeight = Number(data.height) || 520
      root.pinned = data.pinned === true
    }
  }

  FreshTubeCommand {
    id: prefsCmd
    program: root.program
    onFinished: function(code, out, err) {
      if (code !== 0) root.setNotice(root.lastLine(err) || "Could not save preferences", true)
      root.pumpPrefs()
    }
  }

  FreshTubeCommand {
    id: cachedCmd
    program: root.program
    onFinished: function(code, out, err) {
      var data = root.parseJson(out)
      if (code !== 0 || !data) {
        root.setNotice(root.lastLine(err) || "Could not read the cache", true)
        return
      }
      root.applyPayload(data)
    }
  }

  FreshTubeCommand {
    id: refreshCmd
    program: root.program
    timeoutMs: 60000
    onFinished: function(code, out, err) {
      var data = root.parseJson(out)
      if (code !== 0 || !data) {
        root.setNotice(root.lastLine(err) || "Could not refresh", true)
        return
      }
      root.applyPayload(data)
      if (data.offline === true && root.channelCount > 0) {
        var when = Model.formatClock(root.fetchedAt)
        root.setNotice("Offline, showing videos from " + (when !== "" ? when : "the last time"), false)
      } else if (root.errors.length > 0) {
        root.setNotice(root.errors.length + (root.errors.length === 1 ? " channel" : " channels") + " failed to update", false)
      } else if (!root.noticeIsError) {
        root.setNotice("", false)
      }
      if (root.hostWidget && typeof root.hostWidget.broadcast === "function") root.hostWidget.broadcast("reloadCached")
    }
  }

  FreshTubeCommand {
    id: seenCmd
    program: root.program
    onFinished: function(code, out, err) {
      var video = root.pendingPlay
      root.pendingPlay = null
      if (code !== 0) {
        root.setNotice(root.lastLine(err) || "Could not mark it as seen", true)
        return
      }
      var data = root.parseJson(out)
      var id = data ? String(data.seen || "") : ""
      if (id !== "") root.removeVideo(id)
      if (video && !root.pinned) root.close()
    }
  }

  FreshTubeCommand {
    id: playerCheckCmd
    program: "/bin/sh"
    onFinished: function(code, out, err) { root.playerFound = code === 0 }
  }

  FeedPopup {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    pinned: root.pinned
    focusTarget: root.currentFocus
    gripColor: root.foreground
    contentWidth: popup.fittedContentWidth(root.popupWidth)
    contentHeight: popup.cappedContentHeight(root.popupHeight)
    onResizeRequested: function(w, h) {
      root.popupWidth = w
      root.popupHeight = h
    }
    onResized: function(w, h) { root.saveSize(w, h) }

    VideosView {
      id: videosView
      anchors.fill: parent
      visible: root.view === "videos"
      host: root
    }
  }
}
