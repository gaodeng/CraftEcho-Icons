package dev.jahir.blueprint.app

import com.github.javiersantos.piracychecker.PiracyChecker
import dev.jahir.blueprint.ui.activities.BottomNavigationBlueprintActivity

/**
 * You can choose between:
 * - DrawerBlueprintActivity
 * - BottomNavigationBlueprintActivity
 */
class MainActivity : BottomNavigationBlueprintActivity() {

    /**
     * These things here have the default values. You can delete the ones you don't want to change
     * and/or modify the ones you want to.
     */
    // No in-app purchases are configured, so billing is disabled.
    override val billingEnabled = false

    override val isDebug: Boolean = BuildConfig.DEBUG

    // Required by the library, but unused since the license check is disabled.
    override fun getLicKey(): String? = null

    // License check disabled: returning null skips all piracy/licensing checks.
    override fun getLicenseChecker(): PiracyChecker? = null

    override fun defaultTheme(): Int = R.style.MyApp_Default
    override fun amoledTheme(): Int = R.style.MyApp_Default_Amoled

    override fun defaultMaterialYouTheme(): Int = R.style.MyApp_Default_MaterialYou
    override fun amoledMaterialYouTheme(): Int = R.style.MyApp_Default_Amoled_MaterialYou
}
