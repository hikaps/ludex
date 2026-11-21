import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property bool primary: false
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onEnterPressed: if (enabled) clicked()
    property int fontSize: Theme.body

    implicitHeight: 36
    leftPadding: 16
    rightPadding: 16
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus

    contentItem: Txt {
        text: control.text
        font.pixelSize: control.fontSize
        font.bold: control.primary
        color: !control.enabled ? Theme.muted : (control.primary ? "#ffffff" : Theme.text)
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: Theme.radius
        opacity: control.enabled ? 1 : 0.45
        color: control.primary ? (control.down ? Theme.accentDown : control.hovered ? Theme.accentHover : Theme.accent)
                               : (control.down ? Theme.surface2 : control.hovered ? Theme.surface3 : Theme.surface2)
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.text
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
