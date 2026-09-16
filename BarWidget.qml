import QtQuick
import qs.Commons
import qs.Ui

// Bar entry point for Fresh Tube. The panel arrives in a later task; for now
// the icon only proves the plugin loads and sits in the left section.
BarWidget {
  id: root
  moduleName: "io.github.ferc10110.fresh-tube"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰗃"
    fontSize: Style.font.bodySmall
    horizontalMargin: 6
    dimmed: true
    tooltipText: "Fresh Tube"
  }
}
