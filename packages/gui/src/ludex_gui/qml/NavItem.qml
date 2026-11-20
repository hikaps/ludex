import QtQuick

Rectangle {
    id: item
    property string label
    property string glyph
    property string badge
    property bool current: false
    signal activated()

    implicitHeight: 40
    radius: Theme.radius
    color: current ? Theme.surface3 : (mouse.containsMouse ? Theme.surface2 : "transparent")
    Behavior on color { ColorAnimation { duration: 120 } }
    activeFocusOnTab: true
    Keys.onReturnPressed: activated()
    Keys.onSpacePressed: activated()
    border.width: activeFocus ? 1 : 0
    border.color: Theme.accent

    Rectangle {
        width: 3
        height: parent.height - 16
        anchors.verticalCenter: parent.verticalCenter
        radius: 2
        color: Theme.accent
        opacity: item.current ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }
    Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: 16
        spacing: 12
        Txt { text: item.glyph; color: item.current ? Theme.accent : Theme.muted; width: 18; horizontalAlignment: Text.AlignHCenter }
        Txt { text: item.label; color: item.current ? Theme.text : Theme.muted; font.bold: item.current }
    }
    Chip {
        visible: item.badge !== ""
        text: item.badge
        checked: true
        interactive: false
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        anchors.rightMargin: 10
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: item.activated()
    }
}
