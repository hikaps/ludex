import QtQuick
import QtQuick.Controls.Basic

// A switch that a controller or keyboard can flip with Return and see the focus of.
Switch {
    id: control
    Keys.onReturnPressed: { toggle(); toggled() }
    Keys.onEnterPressed: { toggle(); toggled() }
    background: Rectangle {
        color: "transparent"
        radius: Theme.radius
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.text
    }
}
